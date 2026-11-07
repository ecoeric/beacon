// ModelDecodingTests.swift
// Shared by the Xcode unit-test target and the Linux SwiftPM validation harness.
//
// The fixtures in ios/Fixtures were captured from the live backend with
// `scripts/capture_fixtures.sh`, so these tests fail if the API contract drifts.

import XCTest

#if canImport(Beacon)
@testable import Beacon
#else
@testable import BeaconModels
#endif

final class ModelDecodingTests: XCTestCase {
    private func fixture<T: Decodable>(_ name: String, as type: T.Type) throws -> T {
        let directory = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("../Fixtures", isDirectory: true)
        let url = directory.appendingPathComponent(name)
        let data = try Data(contentsOf: url)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    func testHealth() throws {
        let health = try fixture("health.json", as: HealthResponse.self)
        XCTAssertEqual(health.status, "ok")
        XCTAssertEqual(health.database, "ok")
    }

    func testAgentStatusDecodesEnumsAndNestedSession() throws {
        let status = try fixture("agent_status.json", as: AgentStatus.self)
        XCTAssertTrue(AgentState.allCases.contains(status.state))
        XCTAssertFalse(status.stateLabel.isEmpty)
        XCTAssertFalse(status.project.isEmpty)
        XCTAssertNotNil(status.session.id)
        XCTAssertGreaterThanOrEqual(status.queue.pending, 0)
        XCTAssertGreaterThan(status.evidence.count, 0)
        XCTAssertEqual(status.evidence.first?.source, "agent_snapshot")
    }

    func testStatusSummaryIsDeterministicText() throws {
        let summary = try fixture("status_summary.json", as: StatusSummaryResponse.self)
        XCTAssertFalse(summary.summary.isEmpty)
        XCTAssertTrue(summary.deterministic)
        XCTAssertLessThanOrEqual(summary.summary.split(separator: ".").count, 3)
    }

    func testDashboardSummaryDecodesEverything() throws {
        let summary = try fixture("summary.json", as: DashboardSummary.self)
        XCTAssertFalse(summary.services.isEmpty)
        XCTAssertTrue(summary.services.contains { $0.key == "pihole" })
        XCTAssertNotNil(summary.server.memory)
        XCTAssertFalse(summary.server.disks.isEmpty)
        XCTAssertGreaterThanOrEqual(summary.activity.unread, 0)
        // Pi-hole and Minecraft runtime values may legitimately be unavailable in the fixture.
        XCTAssertNotNil(summary.pihole.generatedAt)
        XCTAssertFalse(summary.minecraft.state.isEmpty)
    }

    func testServerOverviewMetrics() throws {
        let server = try fixture("server_overview.json", as: ServerOverview.self)
        XCTAssertGreaterThan(server.cpu.cores, 0)
        XCTAssertFalse(server.cpu.model.isEmpty)
        XCTAssertGreaterThan(server.memory?.totalBytes ?? 0, 0)
        XCTAssertFalse(server.disks.isEmpty)
        XCTAssertNotNil(server.uptimeSeconds)
        if server.gpu.available {
            XCTAssertNotNil(server.gpu.name)
        } else {
            XCTAssertNotNil(server.gpu.error)
        }
    }

    func testPiholeStatus() throws {
        let pihole = try fixture("pihole_status.json", as: PiholeStatus.self)
        if pihole.available {
            XCTAssertNotNil(pihole.blocking)
            XCTAssertNotNil(pihole.queriesTotal)
            XCTAssertNotNil(pihole.percentBlocked)
        } else {
            XCTAssertNotNil(pihole.error)
        }
    }

    func testMinecraftStatusAndProtocolKeyMapping() throws {
        let minecraft = try fixture("minecraft_status.json", as: MinecraftStatus.self)
        XCTAssertEqual(minecraft.state, minecraft.isRunning ? "running" : minecraft.state)
        XCTAssertEqual(minecraft.protocolNumber, 767)
        XCTAssertNotNil(minecraft.controls)
        XCTAssertTrue(minecraft.available)
    }

    func testMinecraftLogs() throws {
        let logs = try fixture("minecraft_logs.json", as: MinecraftLogs.self)
        XCTAssertFalse(logs.lines.isEmpty)
        XCTAssertGreaterThanOrEqual(logs.tickWarnings, 0)
    }

    func testCapabilities() throws {
        let capabilities = try fixture("capabilities.json", as: Capabilities.self)
        XCTAssertEqual(capabilities.messageDelivery.mode, "checkpoint")
        XCTAssertEqual(capabilities.screenshots.maxPerMilestone, 4)
        XCTAssertTrue(capabilities.interrupt.modes.contains("signal"))
        XCTAssertFalse(capabilities.notifications.push)
    }

    func testActivityAndMilestonesDecodeAsArrays() throws {
        let feed = try fixture("activity.json", as: ActivityFeed.self)
        XCTAssertGreaterThanOrEqual(feed.unread, 0)
        let milestones = try fixture("milestones.json", as: [Milestone].self)
        XCTAssertEqual(milestones.count, milestones.count)
    }

    func testQueueMessageContract() throws {
        let json = """
        {"id":"abc","seq":3,"kind":"continue","body":"Continue your work","status":"delivered",
         "created_at":100.0,"delivered_at":101.0,"acknowledged_at":null,"processed_at":null,
         "cancelled_at":null,"attempts":1,"ack_note":null,"processed_note":null}
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let message = try decoder.decode(AgentMessage.self, from: Data(json.utf8))
        XCTAssertEqual(message.kind, .continue)
        XCTAssertEqual(message.status, .delivered)
        XCTAssertEqual(message.attempts, 1)
    }

    func testFormattingHelpers() {
        XCTAssertEqual(Format.bytes(1_048_576), "1 MB")
        XCTAssertEqual(Format.percent(14.4324, digits: 1), "14.4%")
        XCTAssertEqual(Format.duration(90_000), "1d 1h")
        XCTAssertEqual(Format.age(30, now: Date(timeIntervalSince1970: 30)), "just now")
        XCTAssertEqual(Format.age(100, now: Date(timeIntervalSince1970: 130)), "30s ago")
        XCTAssertEqual(Format.age(100, now: Date(timeIntervalSince1970: 1_000)), "15m ago")
        XCTAssertEqual(Format.expiry(1_000, now: Date(timeIntervalSince1970: 2_000)), "expired")
    }

    func testServerConfigurationParsing() {
        XCTAssertNotNil(ServerConfiguration.parse(baseURLString: "192.168.1.83:8091"))
        XCTAssertEqual(ServerConfiguration.parse(baseURLString: "192.168.1.83:8091")?.scheme, "https")
        XCTAssertNotNil(ServerConfiguration.parse(baseURLString: "https://beacon.local:8091"))
        XCTAssertNil(ServerConfiguration.parse(baseURLString: ""))
        let configuration = ServerConfiguration(
            baseURL: URL(string: "https://192.168.1.83:8091")!,
            token: "t",
            spkiPin: nil
        )
        XCTAssertEqual(configuration.displayHost, "192.168.1.83:8091")
        XCTAssertEqual(configuration.endpoint("summary")?.absoluteString, "https://192.168.1.83:8091/api/v1/summary")
        XCTAssertEqual(
            configuration.endpoint("agent/messages", query: [URLQueryItem(name: "limit", value: "5")])?.absoluteString,
            "https://192.168.1.83:8091/api/v1/agent/messages?limit=5"
        )
    }
}
