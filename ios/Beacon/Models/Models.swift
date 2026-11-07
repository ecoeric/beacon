// Models.swift
// Beacon
//
// One-to-one mirrors of the JSON contracts in `backend/beacon/schemas.py`.
// These types import Foundation only, which is what makes them compile and run on Linux
// (see ios/Validation) so decoding can be tested against the live API without a Mac.
//
// Timestamps are Unix epoch seconds (Double); the UI formats them via Formatting.swift.
// JSON keys are decoded with `.convertFromSnakeCase`, so property names are camelCase.

import Foundation

// MARK: - Envelope

struct HealthResponse: Decodable, Equatable {
    let status: String
    let version: String
    let time: Double
    let database: String
    let tls: Bool
}

struct WhoAmI: Decodable, Equatable {
    let tokenId: String
    let name: String
    let scopes: [String]
}

struct APIErrorBody: Decodable {
    let error: String
    let message: String
    let detail: JSONValue?
}

/// Minimal JSON value used only for error `detail` payloads we want to display verbatim.
enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .null
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var displayText: String? {
        switch self {
        case .string(let value): return value
        case .number(let value): return String(format: "%g", value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return nil
        case .object(let dictionary):
            return dictionary.keys.sorted().first.map { "\($0): \(dictionary[$0]?.displayText ?? "")" }
        case .array(let values):
            return values.compactMap(\.displayText).joined(separator: ", ")
        }
    }
}

// MARK: - Agent

enum AgentState: String, Codable, CaseIterable, Identifiable {
    case idle
    case working
    case waitingForInput = "waiting_for_input"
    case waitingForMessages = "waiting_for_messages"
    case completed
    case interrupted
    case failed
    case disconnected
    case unknown

    var id: String { rawValue }

    var title: String {
        switch self {
        case .idle: return "Idle"
        case .working: return "Working"
        case .waitingForInput: return "Waiting for input"
        case .waitingForMessages: return "Queued messages"
        case .completed: return "Completed"
        case .interrupted: return "Interrupted"
        case .failed: return "Failed"
        case .disconnected: return "Disconnected"
        case .unknown: return "Unknown"
        }
    }

    /// Semantic tone used by StatusPill; unknown/disconnected are deliberately neutral-warning
    /// so the UI never implies liveness it cannot prove.
    var tone: Tone {
        switch self {
        case .working: return .accent
        case .idle: return .neutral
        case .completed: return .success
        case .waitingForInput, .waitingForMessages: return .warning
        case .interrupted, .failed, .disconnected: return .danger
        case .unknown: return .neutral
        }
    }

    var symbolName: String {
        switch self {
        case .working: return "bolt.horizontal.circle.fill"
        case .idle: return "moon.stars"
        case .waitingForInput: return "questionmark.bubble"
        case .waitingForMessages: return "tray.full"
        case .completed: return "checkmark.seal.fill"
        case .interrupted: return "pause.circle.fill"
        case .failed: return "exclamationmark.triangle.fill"
        case .disconnected: return "wifi.slash"
        case .unknown: return "questionmark.circle"
        }
    }
}

enum Tone: String, Codable {
    case accent
    case success
    case warning
    case danger
    case neutral
}

struct AgentSessionInfo: Codable, Equatable {
    let id: String?
    let name: String?
    let agentId: String?
    let agentName: String?
    let runtimePid: Int?
    let runtimeAlive: Bool
    let lastActivityAt: Double?
    let lastActivityKind: String?
    let turnRunning: Bool
    let transcriptUpdatedAt: Double?
}

struct EvidenceItem: Codable, Equatable, Identifiable {
    let source: String
    let detail: String
    let ageSeconds: Double?

    var id: String { source + detail }
}

struct QueueCounts: Codable, Equatable {
    let pending: Int
    let delivered: Int
    let acknowledged: Int
    let processedLast24h: Int

    // Foundation's `.convertFromSnakeCase` turns `processed_last_24h` into
    // `processedLast24H` (it upper-cases the first character after every underscore,
    // including digits), so the key is spelled out explicitly.
    enum CodingKeys: String, CodingKey {
        case pending, delivered, acknowledged
        case processedLast24h = "processedLast24H"
    }
}

struct InterruptInfo: Codable, Equatable, Identifiable {
    let id: String
    let requestedAt: Double
    let mode: String
    let status: String
    let reason: String
    let pid: Int?
    let signal: String?
    let resolvedBy: String?
    let exitObservedAt: Double?
    let error: String?
    let evidence: [String]
}

struct AgentStatus: Codable, Equatable {
    let state: AgentState
    let stateLabel: String
    let project: String
    let stage: String
    let activity: String
    let lastMilestone: String
    let nextAction: String
    let blockers: [String]
    let awaitingInput: Bool
    let progress: Double?
    let updatedAt: Double?
    let dataAgeSeconds: Double?
    let isStale: Bool
    let staleAfterSeconds: Int
    let snapshotSource: String
    let session: AgentSessionInfo
    let queue: QueueCounts
    let latestInterrupt: InterruptInfo?
    let evidence: [EvidenceItem]
    let notes: [String]
}

struct StatusSummaryResponse: Codable, Equatable {
    let summary: String
    let state: AgentState
    let generatedAt: Double
    let dataAgeSeconds: Double?
    let isStale: Bool
    let basedOn: [String]
    let deterministic: Bool
}

enum MessageKind: String, Codable {
    case suggestion
    case `continue`

    var title: String {
        switch self {
        case .suggestion: return "Suggestion"
        case .continue: return "Continue"
        }
    }
}

enum MessageStatus: String, Codable {
    case pending
    case delivered
    case acknowledged
    case processed
    case cancelled
    case failed

    var title: String {
        switch self {
        case .pending: return "Queued"
        case .delivered: return "Delivered"
        case .acknowledged: return "Acknowledged"
        case .processed: return "Processed"
        case .cancelled: return "Cancelled"
        case .failed: return "Failed"
        }
    }

    var tone: Tone {
        switch self {
        case .pending: return .warning
        case .delivered, .acknowledged: return .accent
        case .processed: return .success
        case .cancelled: return .neutral
        case .failed: return .danger
        }
    }
}

struct AgentMessage: Codable, Equatable, Identifiable {
    let id: String
    let seq: Int
    let kind: MessageKind
    let body: String
    let status: MessageStatus
    let createdAt: Double
    let deliveredAt: Double?
    let acknowledgedAt: Double?
    let processedAt: Double?
    let cancelledAt: Double?
    let attempts: Int
    let ackNote: String?
    let processedNote: String?
}

struct MessageCreate: Encodable {
    let text: String
    let kind: String
}

struct ContinueRequest: Encodable {
    let note: String?
}

struct InterruptRequest: Encodable {
    let mode: String
    let reason: String?
}

// MARK: - Milestones and screenshots

struct ScreenshotMeta: Codable, Equatable, Identifiable {
    let id: String
    let caption: String
    let source: String
    let contentType: String
    let bytes: Int
    let width: Int?
    let height: Int?
    let createdAt: Double
    let expiresAt: Double
    let url: String
    let sha256: String
    let expired: Bool
}

struct Milestone: Codable, Equatable, Identifiable {
    let id: String
    let seq: Int
    let title: String
    let summary: String
    let changes: [String]
    let phase: String
    let createdAt: Double
    let screenshots: [ScreenshotMeta]
    let expiredScreenshots: Int
}

struct CaptureResult: Codable, Equatable {
    let captureId: String
    let source: String
    let title: String
    let bytes: Int
    let width: Int?
    let height: Int?
    let previewUrl: String
    let expiresAt: Double
}

// MARK: - Server metrics

struct ServiceStatus: Codable, Equatable, Identifiable {
    let key: String
    let label: String
    let state: String
    let summary: String
    let detail: String?
    let checkedAt: Double
    let latencyMs: Double?

    var id: String { key }

    var tone: Tone {
        switch state {
        case "up": return .success
        case "degraded": return .warning
        case "down": return .danger
        case "unknown": return .neutral
        default: return .neutral
        }
    }
}

struct ServerCpu: Codable, Equatable {
    let percent: Double?
    let perCore: [Double]
    let load: [Double]
    let temperatureC: Double?
    let model: String
    let cores: Int
}

struct ServerMemory: Codable, Equatable {
    let totalBytes: Int
    let usedBytes: Int
    let availableBytes: Int
    let percent: Double
    let swapTotalBytes: Int
    let swapUsedBytes: Int
    let swapPercent: Double
}

struct ServerGpu: Codable, Equatable {
    let available: Bool
    let name: String?
    let utilizationPercent: Double?
    let temperatureC: Double?
    let memoryUsedBytes: Int?
    let memoryTotalBytes: Int?
    let powerW: Double?
    let error: String?
}

struct DiskUsage: Codable, Equatable, Identifiable {
    let mount: String
    let filesystem: String
    let totalBytes: Int
    let usedBytes: Int
    let freeBytes: Int
    let percent: Double

    var id: String { mount }
}

struct NetworkThroughput: Codable, Equatable {
    let interface: String
    let rxBytesPerSecond: Double
    let txBytesPerSecond: Double
    let rxBytesTotal: Int
    let txBytesTotal: Int
}

struct DockerContainerInfo: Codable, Equatable, Identifiable {
    let name: String
    let image: String
    let state: String
    let status: String
    let health: String?
    let cpuPercent: Double?
    let memoryBytes: Int?
    let memoryLimitBytes: Int?
    let startedAt: Double?
    let error: String?

    var id: String { name }
}

struct ServerOverview: Codable, Equatable {
    let generatedAt: Double
    let uptimeSeconds: Double?
    let cpu: ServerCpu
    let memory: ServerMemory?
    let gpu: ServerGpu
    let disks: [DiskUsage]
    let network: NetworkThroughput?
    let docker: [DockerContainerInfo]
    let dockerAvailable: Bool
    let dockerError: String?
    let unavailable: [String]
}

// MARK: - Pi-hole

struct DomainCount: Codable, Equatable, Identifiable {
    let name: String
    let count: Int

    var id: String { name }
}

struct UpstreamInfo: Codable, Equatable, Identifiable {
    let name: String
    let address: String
    let count: Int
    let responseAvgMs: Double?

    var id: String { name + address }
}

struct PiholeStatus: Codable, Equatable {
    let available: Bool
    let online: Bool
    let blocking: String?
    let container: DockerContainerInfo?
    let queriesTotal: Int?
    let queriesBlocked: Int?
    let percentBlocked: Double?
    let uniqueDomains: Int?
    let queriesForwarded: Int?
    let queriesCached: Int?
    let topBlockedDomains: [DomainCount]
    let topClients: [DomainCount]
    let upstreams: [UpstreamInfo]
    let generatedAt: Double
    let error: String?

    var isBlocking: Bool { blocking == "enabled" }
}

// MARK: - Minecraft

struct MinecraftControls: Codable, Equatable {
    let available: Bool
    let actions: [String]
    let stopMethod: String?
    let startMethod: String?
    let reason: String?
}

struct MinecraftStatus: Codable, Equatable {
    let available: Bool
    let online: Bool
    let state: String
    let version: String?
    let protocolNumber: Int?
    let motd: String?
    let playersOnline: Int?
    let playersMax: Int?
    let players: [String]
    let uptimeSeconds: Double?
    let pid: Int?
    let cpuPercent: Double?
    let memoryBytes: Int?
    let tps: Double?
    let mspt: Double?
    let tickMetricsNote: String?
    let recentErrors: [String]
    let recentEvents: [String]
    let logUpdatedAt: Double?
    let lastBackupAt: Double?
    let backupNote: String?
    let controls: MinecraftControls
    let generatedAt: Double
    let error: String?

    var isRunning: Bool { state == "running" }

    enum CodingKeys: String, CodingKey {
        case available, online, state, version, motd, players, uptimeSeconds, pid
        case protocolNumber = "protocol"
        case cpuPercent, memoryBytes, tps, mspt, tickMetricsNote
        case playersOnline, playersMax, recentErrors, recentEvents, logUpdatedAt
        case lastBackupAt, backupNote, controls, generatedAt, error
    }
}

struct MinecraftLogs: Codable, Equatable {
    let lines: [String]
    let errors: [String]
    let events: [String]
    let tickWarnings: Int
    let updatedAt: Double?
}

// MARK: - Activity

struct ActivityItem: Codable, Equatable, Identifiable {
    let id: String
    let kind: String
    let severity: String
    let title: String
    let body: String
    let createdAt: Double
    let readAt: Double?
    let payload: [String: JSONValue]

    var isRead: Bool { readAt != nil }

    var tone: Tone {
        switch severity {
        case "success": return .success
        case "warning": return .warning
        case "error": return .danger
        default: return .accent
        }
    }
}

struct ActivityFeed: Codable, Equatable {
    let unread: Int
    let items: [ActivityItem]
}

// MARK: - Dashboard

struct DashboardSummary: Codable, Equatable {
    let generatedAt: Double
    let agent: AgentStatus
    let services: [ServiceStatus]
    let server: ServerOverview
    let pihole: PiholeStatus
    let minecraft: MinecraftStatus
    let latestMilestone: Milestone?
    let activity: ActivityFeed
    let dataAgeSeconds: Double?
}

struct Capabilities: Decodable, Equatable {
    struct AgentSection: Decodable, Equatable {
        let bindingMode: String
        let configuredAgentId: String?
        let statusSource: String
    }
    struct DeliverySection: Decodable, Equatable {
        let mode: String
        let maxMessageChars: Int
    }
    struct InterruptSection: Decodable, Equatable {
        let modes: [String]
        let signal: String
    }
    struct ScreenshotSection: Decodable, Equatable {
        let retentionDays: Int
        let sources: [String]
        let maxPerMilestone: Int
    }
    struct MonitoringSection: Decodable, Equatable {
        let docker: Bool
        let dockerError: String?
        let gpu: Bool
        let gpuError: String?
        let cpuTemperature: Bool
        let minecraftTickMetrics: Bool
        let minecraftControlActions: [String]
        let pihole: Bool
    }
    struct NotificationSection: Decodable, Equatable {
        let inApp: Bool
        let push: Bool
        let pushNote: String
    }

    let agent: AgentSection
    let messageDelivery: DeliverySection
    let interrupt: InterruptSection
    let screenshots: ScreenshotSection
    let monitoring: MonitoringSection
    let notifications: NotificationSection
}
