// AppModel.swift
// Beacon
//
// Single observable source of truth for the app: configuration, connection state, dashboard
// data, milestone history and user actions. Views never talk to the network directly.

import Combine
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    enum Connection: Equatable {
        case unknown
        case checking
        case online(version: String)
        case unauthorized
        case offline(String)

        var label: String {
            switch self {
            case .unknown: return "Not connected"
            case .checking: return "Connecting…"
            case .online(let version): return "Connected · v\(version)"
            case .unauthorized: return "Token rejected"
            case .offline: return "Offline"
            }
        }

        var tone: Tone {
            switch self {
            case .online: return .success
            case .checking, .unknown: return .neutral
            case .unauthorized, .offline: return .danger
            }
        }

        var isOnline: Bool {
            if case .online = self { return true }
            return false
        }
    }

    // Connection & configuration
    @Published private(set) var connection: Connection = .unknown
    @Published private(set) var isConfigured = false
    @Published private(set) var identityName: String?
    @Published private(set) var tokenScopes: [String] = []
    @Published private(set) var hostLabel: String = ""

    // Data
    @Published private(set) var summary: DashboardSummary?
    @Published private(set) var milestones: [Milestone] = []
    @Published private(set) var messages: [AgentMessage] = []
    @Published private(set) var activity: ActivityFeed?
    @Published private(set) var capabilities: Capabilities?
    @Published private(set) var backendVersion: String?

    // UI state
    @Published private(set) var isRefreshing = false
    @Published private(set) var isPerformingAction = false
    @Published private(set) var isStatusLoading = false
    @Published var errorMessage: String?

    @Published private(set) var lastUpdated: Date?
    @Published private(set) var setupError: String?
    @Published private(set) var statusSummary: StatusSummaryResponse?

    private let settings: AppSettings
    private var client: APIClient?
    private var session: URLSession?
    private var pollTask: Task<Void, Never>?
    private var previewMode = false

    init(settings: AppSettings = .shared) {
        self.settings = settings
        reconfigure()
    }

    // MARK: - Configuration

    private func reconfigure() {
        session?.invalidateAndCancel()
        if previewMode { return }
        guard let configuration = settings.configured() else {
            client = nil
            session = nil
            isConfigured = false
            hostLabel = settings.baseURLString
            return
        }
        let session = PinnedSessionFactory.make(configuration: configuration)
        self.session = session
        client = APIClient(configuration: configuration, session: session)
        isConfigured = true
        hostLabel = configuration.displayHost
    }

    func bootstrap() async {
        reconfigure()
        guard isConfigured else {
            connection = .unknown
            return
        }
        connection = .checking
        do {
            let health = try await client?.health()
            backendVersion = health?.version
            if let health {
                connection = .online(version: health.version)
            }
            if let identity = try await client?.whoAmI() {
                identityName = identity.name
                tokenScopes = identity.scopes
            }
            await refresh(showSpinner: false)
            await refreshMilestones()
            await loadCapabilities()
            startPolling()
        } catch {
            handle(error, prefix: "Connecting")
        }
    }

    func signIn(baseURLString: String, token: String, pin: String?) async -> Bool {
        setupError = nil
        guard let url = ServerConfiguration.parse(baseURLString: baseURLString) else {
            setupError = "That server address is not valid."
            return false
        }
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedToken.isEmpty else {
            setupError = "A token is required. Run `beacon token create ios --scopes read,action,admin`."
            return false
        }
        let trimmedPin = pin?.trimmingCharacters(in: .whitespacesAndNewlines)
        let configuration = ServerConfiguration(
            baseURL: url,
            token: trimmedToken,
            spkiPin: (trimmedPin?.isEmpty ?? true) ? nil : trimmedPin
        )
        let testSession = PinnedSessionFactory.make(configuration: configuration)
        let testClient = APIClient(configuration: configuration, session: testSession)
        do {
            _ = try await testClient.health()
            let identity = try await testClient.whoAmI()
            tokenScopes = identity.scopes
            try settings.save(baseURLString: url.absoluteString, token: trimmedToken, pin: configuration.spkiPin)
            testSession.invalidateAndCancel()
            identityName = identity.name
            reconfigure()
            connection = .online(version: backendVersion ?? "?")
            await refresh()
            await refreshMilestones()
            await loadCapabilities()
            startPolling()
            return true
        } catch {
            testSession.invalidateAndCancel()
            setupError = message(for: error)
            return false
        }
    }

    func signOut() {
        stopPolling()
        settings.clear()
        session?.invalidateAndCancel()
        session = nil
        client = nil
        summary = nil
        milestones = []
        messages = []
        activity = nil
        capabilities = nil
        statusSummary = nil
        identityName = nil
        tokenScopes = []
        lastUpdated = nil
        isConfigured = false
        connection = .unknown
        errorMessage = nil
    }

    // MARK: - Refresh

    func refresh(showSpinner: Bool = true) async {
        guard let client else { return }
        if isRefreshing { return }
        if showSpinner { isRefreshing = true }
        defer { isRefreshing = false }
        do {
            let summary = try await client.summary()
            self.summary = summary
            self.activity = summary.activity
            if let messages = try? await client.messages(limit: 12) {
                self.messages = messages
            }
            self.lastUpdated = Date()
            if !connection.isOnline {
                connection = .online(version: backendVersion ?? "?")
            }
            errorMessage = nil
        } catch {
            handle(error, prefix: "Refresh")
        }
    }

    func refreshMilestones() async {
        guard let client else { return }
        do {
            milestones = try await client.milestoneList()
        } catch {
            if milestones.isEmpty {
                handle(error, prefix: "Milestones")
            }
        }
    }

    func loadActivity() async {
        guard let client else { return }
        do {
            activity = try await client.activity()
        } catch {
            handle(error, prefix: "Activity")
        }
    }

    func loadCapabilities() async {
        guard let client else { return }
        capabilities = try? await client.capabilities()
    }

    // MARK: - Agent

    func loadStatusSummary() async {
        guard let client else { return }
        isStatusLoading = true
        defer { isStatusLoading = false }
        do {
            statusSummary = try await client.statusSummary()
        } catch {
            handle(error, prefix: "Status")
        }
    }

    struct MessageFeedback {
        let success: Bool
        let text: String
    }

    func sendSuggestion(_ text: String) async -> MessageFeedback {
        guard let client else { return .init(success: false, text: "Not connected") }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let message = try await client.sendSuggestion(text)
            await refresh(showSpinner: false)
            return .init(success: true, text: "Queued as #\(message.seq) — the agent picks it up at its next checkpoint.")
        } catch {
            handle(error, prefix: "Sending")
            return .init(success: false, text: message(for: error))
        }
    }

    func continueWork(note: String?) async -> MessageFeedback {
        guard let client else { return .init(success: false, text: "Not connected") }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let message = try await client.sendContinue(note: note)
            await refresh(showSpinner: false)
            return .init(success: true, text: "Continue queued as #\(message.seq).")
        } catch {
            handle(error, prefix: "Continue")
            return .init(success: false, text: message(for: error))
        }
    }

    func interruptAgent(mode: String, reason: String) async -> MessageFeedback {
        guard let client else { return .init(success: false, text: "Not connected") }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let interrupt = try await client.requestInterrupt(mode: mode, reason: reason)
            await refresh(showSpinner: false)
            let detail = interrupt.pid.map { "pid \($0)" } ?? interrupt.mode
            return .init(success: true, text: "Interrupt \(interrupt.status) (\(detail)).")
        } catch {
            handle(error, prefix: "Interrupt")
            return .init(success: false, text: message(for: error))
        }
    }

    func cancelMessage(id: String) async {
        guard let client else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.cancelMessage(id: id)
            await refresh(showSpinner: false)
        } catch {
            handle(error, prefix: "Cancel")
        }
    }

    // MARK: - Services

    func togglePihole(enabled: Bool) async -> MessageFeedback {
        guard let client else { return .init(success: false, text: "Not connected") }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let status = try await client.setPiholeBlocking(enabled: enabled)
            await refresh(showSpinner: false)
            return .init(success: true, text: "Blocking is now \(status.blocking ?? "unknown").")
        } catch {
            handle(error, prefix: "Pi-hole")
            return .init(success: false, text: message(for: error))
        }
    }

    func minecraftAction(_ action: String, force: Bool = false) async -> MessageFeedback {
        guard let client else { return .init(success: false, text: "Not connected") }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.minecraftControl(action: action, force: force)
            await refresh(showSpinner: false)
            return .init(success: true, text: "Minecraft \(action) requested.")
        } catch {
            handle(error, prefix: "Minecraft")
            return .init(success: false, text: message(for: error))
        }
    }

    func minecraftLogs() async throws -> MinecraftLogs {
        guard let client else { throw BeaconError.notConfigured }
        return try await client.minecraftLogs()
    }

    // MARK: - Activity

    func markActivityRead(id: String) async {
        guard let client else { return }
        try? await client.markActivityRead(id: id)
        await loadActivity()
    }

    func markAllActivityRead() async {
        guard let client else { return }
        try? await client.markAllActivityRead()
        await loadActivity()
    }

    // MARK: - Images

    func screenshotData(id: String) async throws -> Data {
        if let data = previewScreenshots[id] { return data }
        guard let client else { throw BeaconError.notConfigured }
        return try await client.screenshotData(id: id)
    }

    // MARK: - Polling

    func startPolling() {
        guard pollTask == nil, isConfigured, !previewMode else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                if Task.isCancelled { return }
                guard let self else { return }
                await self.refresh(showSpinner: false)
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    // MARK: - Convenience

    var agent: AgentStatus? { summary?.agent }
    var pihole: PiholeStatus? { summary?.pihole }
    var minecraft: MinecraftStatus? { summary?.minecraft }
    var server: ServerOverview? { summary?.server }
    var latestMilestone: Milestone? { summary?.latestMilestone ?? milestones.first }
    var unreadActivity: Int { activity?.unread ?? summary?.activity.unread ?? 0 }

    var freshnessText: String {
        guard let stamp = lastUpdated else { return "Not loaded yet" }
        return "Updated \(Format.age(stamp.timeIntervalSince1970))"
    }

    private func handle(_ error: Error, prefix _: String) {
        let text = message(for: error)
        errorMessage = text
        if let beacon = error as? BeaconError {
            switch beacon {
            case .unauthorized, .forbidden:
                connection = .unauthorized
            case .transport, .trust, .decoding, .server:
                connection = .offline(text)
            default:
                break
            }
        }
    }

    private func message(for error: Error) -> String {
        (error as? BeaconError)?.localizedDescription ?? error.localizedDescription
    }

    // MARK: - Previews & snapshot tests

    /// Snapshot tests and previews can supply real image bytes for the gallery tiles.
    var previewScreenshots: [String: Data] = [:]

    /// Lets the snapshot test target render a live payload without exposing data setters.
    func injectForSnapshots(
        summary: DashboardSummary,
        milestones: [Milestone],
        capabilities: Capabilities?,
        version: String
    ) {
        previewMode = true
        isConfigured = true
        connection = .online(version: version)
        backendVersion = version
        self.summary = summary
        self.activity = summary.activity
        self.milestones = milestones
        self.capabilities = capabilities
        lastUpdated = Date()
    }

    static func preview(summary: DashboardSummary, milestones: [Milestone] = []) -> AppModel {
        let model = AppModel()
        model.previewMode = true
        model.isConfigured = true
        model.connection = .online(version: "0.1.0")
        model.identityName = "ios"
        model.hostLabel = "192.168.1.83:8091"
        model.backendVersion = "0.1.0"
        model.summary = summary
        model.activity = summary.activity
        model.milestones = milestones
        model.lastUpdated = Date()
        return model
    }
}
