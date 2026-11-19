// APIClient.swift
// Beacon
//
// Thin async/await wrapper over the Beacon API. No third-party dependencies.
// Foundation only (plus FoundationNetworking on Linux) so the decoding and error mapping
// can be unit-tested without a simulator.

import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum BeaconError: LocalizedError, Equatable {
    case notConfigured
    case badURL
    case unauthorized
    case forbidden(String)
    case confirmationRequired(String)
    case notFound
    case gone(String)
    case rateLimited(retryAfter: TimeInterval?)
    case server(status: Int, code: String, message: String)
    case transport(String)
    case trust(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "No server configured"
        case .badURL:
            return "That server address is not valid"
        case .unauthorized:
            return "The token was rejected. Check the token in Settings."
        case .forbidden(let message):
            return message.isEmpty ? "This token is not allowed to do that" : message
        case .confirmationRequired(let message):
            return message
        case .notFound:
            return "Not found on the server"
        case .gone(let message):
            return message
        case .rateLimited:
            return "Too many requests — try again in a moment"
        case .server(_, _, let message):
            return message
        case .transport(let message):
            return message
        case .trust(let message):
            return message
        case .decoding(let message):
            return "Unexpected server response: \(message)"
        }
    }

    var isOffline: Bool {
        if case .transport = self { return true }
        return false
    }

    var needsTrustDecision: Bool {
        if case .trust = self { return true }
        return false
    }
}

struct APIClient {
    let configuration: ServerConfiguration
    let session: URLSession

    init(configuration: ServerConfiguration, session: URLSession = .shared) {
        self.configuration = configuration
        self.session = session
    }

    private var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }

    // MARK: - Transport

    private func request(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = [],
        body: Encodable? = nil,
        extraHeaders: [String: String] = [:]
    ) async throws -> Data {
        guard let url = configuration.endpoint(path, query: query) else { throw BeaconError.badURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
        request.setValue("Beacon/1.0 (iOS)", forHTTPHeaderField: "User-Agent")
        for (key, value) in extraHeaders {
            request.setValue(value, forHTTPHeaderField: key)
        }
        if let body {
            request.httpBody = try encoder.encode(AnyEncodable(body))
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return try await perform(request)
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            if error.code == .serverCertificateUntrusted ||
                error.code == .serverCertificateHasUnknownRoot ||
                error.code == .serverCertificateHasBadDate ||
                error.code == .secureConnectionFailed {
                throw BeaconError.trust(
                    "The server certificate is not trusted. Install the matching CA (ios/Beacon/Resources/ca.crt) and pin."
                )
            }
            throw BeaconError.transport(Self.message(for: error, host: request.url?.host))
        } catch {
            throw BeaconError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw BeaconError.transport("No HTTP response")
        }
        switch http.statusCode {
        case 200..<300:
            return data
        case 401:
            throw BeaconError.unauthorized
        case 403:
            throw BeaconError.forbidden(Self.errorMessage(from: data) ?? "This token is not allowed to do that")
        case 404:
            if let message = Self.errorMessage(from: data) { throw BeaconError.gone(message) }
            throw BeaconError.notFound
        case 410:
            throw BeaconError.gone(Self.errorMessage(from: data) ?? "No longer available")
        case 428:
            throw BeaconError.confirmationRequired(
                Self.errorMessage(from: data) ?? "This action needs confirmation"
            )
        case 429:
            throw BeaconError.rateLimited(retryAfter: http.value(forHTTPHeaderField: "Retry-After").flatMap(TimeInterval.init))
        default:
            let payload = try? decoder.decode(APIErrorBody.self, from: data)
            throw BeaconError.server(
                status: http.statusCode,
                code: payload?.error ?? "http_\(http.statusCode)",
                message: payload?.message ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            )
        }
    }

    private static func errorMessage(from data: Data) -> String? {
        guard let payload = try? JSONDecoder().decode(APIErrorBody.self, from: data) else { return nil }
        return payload.message
    }

    private static func message(for error: URLError, host: String?) -> String {
        let target = host.map { "\($0)" } ?? "the server"
        switch error.code {
        case .cannotFindHost, .dnsLookupFailed:
            return "Cannot find \(target). Check the address in Settings."
        case .cannotConnectToHost:
            return "Cannot reach \(target). Is Beacon running and are you on the same network?"
        case .timedOut:
            return "\(target) did not answer in time. The server may be busy or asleep."
        case .networkConnectionLost, .notConnectedToInternet:
            return "Network connection lost. Showing the last known data."
        case .appTransportSecurityRequiresSecureConnection:
            return "iOS blocked a non-HTTPS connection. Use the https:// address of the Beacon server."
        default:
            return error.localizedDescription
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw BeaconError.decoding(String(describing: error))
        }
    }

    // MARK: - Endpoints

    func health() async throws -> HealthResponse {
        let data = try await request("GET", "health")
        return try decode(HealthResponse.self, from: data)
    }

    func whoAmI() async throws -> WhoAmI {
        let data = try await request("GET", "whoami")
        return try decode(WhoAmI.self, from: data)
    }

    func summary() async throws -> DashboardSummary {
        let data = try await request("GET", "summary")
        return try decode(DashboardSummary.self, from: data)
    }

    func capabilities() async throws -> Capabilities {
        let data = try await request("GET", "capabilities")
        return try decode(Capabilities.self, from: data)
    }

    func agentStatus() async throws -> AgentStatus {
        let data = try await request("GET", "agent/status")
        return try decode(AgentStatus.self, from: data)
    }

    /// Read-only Status action: the backend composes this from the structured snapshot.
    /// No prompt is sent, no inference runs, nothing is added to the conversation.
    func statusSummary() async throws -> StatusSummaryResponse {
        let data = try await request("GET", "agent/status/summary")
        return try decode(StatusSummaryResponse.self, from: data)
    }

    func messages(limit: Int = 20) async throws -> [AgentMessage] {
        let data = try await request("GET", "agent/messages", query: [URLQueryItem(name: "limit", value: "\(limit)")])
        return try decode([AgentMessage].self, from: data)
    }

    func sendSuggestion(_ text: String, idempotencyKey: String? = nil) async throws -> AgentMessage {
        struct Body: Encodable {
            let text: String
            let kind: String
            let idempotencyKey: String?
        }
        let payload = Body(text: text, kind: "suggestion", idempotencyKey: idempotencyKey)
        let data = try await request("POST", "agent/messages", body: payload)
        return try decode(AgentMessage.self, from: data)
    }

    func sendContinue(note: String?) async throws -> AgentMessage {
        let body = ContinueRequest(note: (note?.isEmpty ?? true) ? nil : note)
        let data = try await request("POST", "agent/continue", body: body)
        return try decode(AgentMessage.self, from: data)
    }

    func cancelMessage(id: String) async throws -> AgentMessage {
        let data = try await request("DELETE", "agent/messages/\(id)")
        return try decode(AgentMessage.self, from: data)
    }

    /// Out-of-band interruption. Uses the dedicated endpoint, never the message queue.
    func agentSessions(limit: Int = 20) async throws -> [AgentSessionSummary] {
        let data = try await request(
            "GET", "agent/sessions",
            query: [URLQueryItem(name: "limit", value: "\(limit)")]
        )
        return try decoder.decode([AgentSessionSummary].self, from: data)
    }

    func agentSessionMessages(sessionId: String, limit: Int = 200) async throws -> [AgentChatMessage] {
        let data = try await request(
            "GET", "agent/sessions/\(sessionId)/messages",
            query: [URLQueryItem(name: "limit", value: "\(limit)")]
        )
        return try decoder.decode([AgentChatMessage].self, from: data)
    }

    func sendChatMessage(sessionId: String, text: String, clientMessageId: String) async throws -> ChatSendResult {
        struct Body: Encodable {
            let text: String
            let clientMessageId: String
        }
        let body = Body(text: text, clientMessageId: clientMessageId)
        let data = try await request("POST", "agent/sessions/\(sessionId)/messages", body: body)
        return try decode(ChatSendResult.self, from: data)
    }

    func requestInterrupt(mode: String, reason: String) async throws -> InterruptInfo {
        let body = InterruptRequest(mode: mode, reason: reason)
        let data = try await request(
            "POST",
            "agent/interrupt",
            body: body,
            extraHeaders: ["X-Beacon-Confirm": "agent-interrupt"]
        )
        return try decode(InterruptInfo.self, from: data)
    }

    func milestoneList(limit: Int = 20) async throws -> [Milestone] {
        let data = try await request("GET", "milestones", query: [URLQueryItem(name: "limit", value: "\(limit)")])
        return try decode([Milestone].self, from: data)
    }

    func screenshotData(id: String) async throws -> Data {
        try await request("GET", "screenshots/\(id)")
    }

    func serverOverview() async throws -> ServerOverview {
        let data = try await request("GET", "server/overview")
        return try decode(ServerOverview.self, from: data)
    }

    func piholeStatus() async throws -> PiholeStatus {
        let data = try await request("GET", "pihole/status")
        return try decode(PiholeStatus.self, from: data)
    }

    func setPiholeBlocking(enabled: Bool) async throws -> PiholeStatus {
        struct Body: Encodable { let enabled: Bool }
        _ = try await request(
            "POST",
            "pihole/blocking",
            body: Body(enabled: enabled),
            extraHeaders: ["X-Beacon-Confirm": "pihole-blocking"]
        )
        return try await piholeStatus()
    }

    func minecraftStatus() async throws -> MinecraftStatus {
        let data = try await request("GET", "minecraft/status")
        return try decode(MinecraftStatus.self, from: data)
    }

    func minecraftLogs(lines: Int = 80) async throws -> MinecraftLogs {
        let data = try await request("GET", "minecraft/logs", query: [URLQueryItem(name: "lines", value: "\(lines)")])
        return try decode(MinecraftLogs.self, from: data)
    }

    func minecraftControl(action: String, force: Bool = false) async throws -> String {
        struct Body: Encodable {
            let action: String
            let force: Bool
        }
        let data = try await request(
            "POST",
            "minecraft/control",
            body: Body(action: action, force: force),
            extraHeaders: ["X-Beacon-Confirm": "minecraft-\(action)"]
        )
        return String(data: data, encoding: .utf8) ?? "ok"
    }

    func activity(limit: Int = 30) async throws -> ActivityFeed {
        let data = try await request("GET", "activity", query: [URLQueryItem(name: "limit", value: "\(limit)")])
        return try decode(ActivityFeed.self, from: data)
    }

    func markActivityRead(id: String) async throws {
        _ = try await request("POST", "activity/\(id)/read")
    }

    func markAllActivityRead() async throws {
        _ = try await request("POST", "activity/read-all")
    }
}

// MARK: - helpers

/// Type eraser so `request` can take any Encodable payload without generics leaking.
struct AnyEncodable: Encodable {
    private let value: Encodable

    init(_ value: Encodable) {
        self.value = value
    }

    func encode(to encoder: Encoder) throws {
        try value.encode(to: encoder)
    }
}
