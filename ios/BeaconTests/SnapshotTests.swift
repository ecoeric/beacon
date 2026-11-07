// SnapshotTests.swift
// BeaconTests (unit-test target hosted by the app; run with xcodebuild on macOS)
//
// Renders the four key screens to PNG files. Two modes:
//
//   * Live:   BEACON_SNAPSHOT_BASE_URL + BEACON_SNAPSHOT_TOKEN are set -> the real backend is
//             queried, real milestone screenshots are fetched, and the rendered images are
//             genuine captures of the application showing live data.
//   * Layout: no environment -> DEBUG fixtures are rendered, so layout can be reviewed without
//             a server. Screenshot tiles show "Unavailable" rather than invented images.
//
//   xcodebuild test -project ios/Beacon.xcodeproj -scheme Beacon \
//     -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
//     -only-testing:BeaconTests/SnapshotTests \
//     BEACON_SNAPSHOT_DIR=$HOME/beacon/artifacts/snapshots
//
// `scripts/publish_snapshots.py` then attaches those PNGs to a milestone on the server.

import SwiftUI
import XCTest

@testable import Beacon

@MainActor
final class SnapshotTests: XCTestCase {
    private var outputDirectory: URL {
        let raw = ProcessInfo.processInfo.environment["BEACON_SNAPSHOT_DIR"]
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("beacon-snapshots").path
        return URL(fileURLWithPath: raw, isDirectory: true)
    }

    private var liveConfiguration: ServerConfiguration? {
        let environment = ProcessInfo.processInfo.environment
        guard let host = environment["BEACON_SNAPSHOT_BASE_URL"],
              let token = environment["BEACON_SNAPSHOT_TOKEN"],
              let url = ServerConfiguration.parse(baseURLString: host) else {
            return nil
        }
        let pin = environment["BEACON_SNAPSHOT_PIN"]
        return ServerConfiguration(baseURL: url, token: token, spkiPin: (pin?.isEmpty ?? true) ? nil : pin)
    }

    func testCaptureFourScreens() async throws {
        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

        let model: AppModel
        if let configuration = liveConfiguration {
            model = try await liveModel(configuration: configuration)
        } else {
            model = AppModel.preview(summary: Fixtures.dashboard, milestones: Fixtures.milestones)
        }

        let screens: [(file: String, caption: String, view: AnyView)] = [
            (
                "01-home-dashboard.png",
                "Home dashboard: live agent card, service health, host metrics and the latest milestone gallery",
                AnyView(DashboardView(onOpenAgent: {}).environmentObject(model))
            ),
            (
                "02-agent-panel.png",
                "Agent panel: structured status, queued instruction composer, recent delivery states and the separate interrupt action",
                AnyView(AgentView().environmentObject(model))
            ),
            (
                "03-milestone-gallery.png",
                "Progress: milestone history with the 2x2 screenshot gallery and retention notes",
                AnyView(MilestonesView().environmentObject(model))
            ),
            (
                "04-server-services.png",
                "Server: host metrics, Pi-hole and Minecraft monitoring with guarded controls",
                AnyView(ServerView().environmentObject(model))
            )
        ]

        for screen in screens {
            try render(screen.view, to: outputDirectory.appendingPathComponent(screen.file), caption: screen.caption)
        }
        try writeManifest(screens.map { ($0.file, $0.caption) })
    }

    private func liveModel(configuration: ServerConfiguration) async throws -> AppModel {
        let session = PinnedSessionFactory.make(configuration: configuration)
        let client = APIClient(configuration: configuration, session: session)
        let health = try await client.health()
        let summary = try await client.summary()
        let milestones = try await client.milestoneList()
        let capabilities = try? await client.capabilities()

        for milestone in milestones {
            for shot in milestone.screenshots where !shot.expired {
                if let data = try? await client.screenshotData(id: shot.id), let image = UIImage(data: data) {
                    AsyncScreenshotCache.images[shot.id] = image
                }
            }
        }

        let model = AppModel()
        model.injectForSnapshots(
            summary: summary,
            milestones: milestones,
            capabilities: capabilities,
            version: health.version
        )
        return model
    }

    private func render(_ view: AnyView, to url: URL, caption: String) throws {
        let renderer = ImageRenderer(content: view.frame(width: 393, height: 852))
        renderer.scale = 3
        renderer.isOpaque = false
        guard let image = renderer.uiImage, let data = image.pngData() else {
            XCTFail("ImageRenderer produced no image for \(url.lastPathComponent)")
            return
        }
        try data.write(to: url)
        print("snapshot: \(url.path) - \(caption)")
    }

    private func writeManifest(_ screens: [(String, String)]) throws {
        let payload: [String: Any] = [
            "generated_at": ISO8601DateFormatter().string(from: Date()),
            "device": "iPhone 16 Pro (snapshot renderer, 393x852 @3x)",
            "screens": screens.map { ["file": $0.0, "caption": $0.1] }
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: outputDirectory.appendingPathComponent("manifest.json"))
    }
}
