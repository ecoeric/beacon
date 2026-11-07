// Fixtures.swift
// Beacon
//
// Sample data for SwiftUI previews and the layout snapshot test target. Compiled only in
// DEBUG builds. Values mirror the real API shapes captured in ios/Fixtures/*.json.

import Foundation

enum Fixtures {
    static let now = Date().timeIntervalSince1970

    static func screenshot(_ index: Int) -> ScreenshotMeta {
        ScreenshotMeta(
            id: String(format: "sample-shot-%02d", index),
            caption: [
                "Home dashboard with live agent card",
                "Agent panel with queued message",
                "Milestone gallery, 2×2",
                "Host metrics detail"
            ][index],
            source: "text",
            contentType: "image/png",
            bytes: 128_000,
            width: 1120,
            height: 720,
            createdAt: now - Double(index) * 90,
            expiresAt: now + 6 * 86_400,
            url: "/api/v1/screenshots/sample-\(index)",
            sha256: String(repeating: "a", count: 64),
            expired: false
        )
    }

    static let session = AgentSessionInfo(
        id: "229a4178-607d-4c20-831c-0c8f4e50468f",
        name: "Beacon dashboard build",
        agentId: "cc33efa9-6b9f-41f0-bf75-86dbc6e27096",
        agentName: "agent",
        runtimePid: 415_932,
        runtimeAlive: true,
        lastActivityAt: now - 12,
        lastActivityKind: "Assistant turn running",
        turnRunning: true,
        transcriptUpdatedAt: now - 8
    )

    static let agent = AgentStatus(
        state: .working,
        stateLabel: "Working",
        project: "Beacon — native iOS server dashboard",
        stage: "Phase 2: native iOS foundation",
        activity: "Writing the SwiftUI dashboard and agent panel",
        lastMilestone: "Phase 1 discovery and architecture verified",
        nextAction: "Wire the message queue and interrupt flows",
        blockers: [],
        awaitingInput: false,
        progress: 0.42,
        updatedAt: now - 20,
        dataAgeSeconds: 20,
        isStale: false,
        staleAfterSeconds: 90,
        snapshotSource: "agent",
        session: session,
        queue: QueueCounts(pending: 1, delivered: 0, acknowledged: 0, processedLast24h: 3),
        latestInterrupt: nil,
        evidence: [
            EvidenceItem(source: "agent_snapshot", detail: "Pushed by agent at \(Int(now - 20))", ageSeconds: 20),
            EvidenceItem(source: "cherry_session", detail: "agent · Beacon dashboard build", ageSeconds: 12),
            EvidenceItem(source: "runtime_process", detail: "pid 415932 serving this session", ageSeconds: nil),
            EvidenceItem(source: "message_queue", detail: "1 pending · 0 delivered · 0 acknowledged", ageSeconds: nil)
        ],
        notes: []
    )

    static let services = [
        ServiceStatus(key: "api", label: "Dashboard API", state: "up", summary: "Responding", detail: nil, checkedAt: now, latencyMs: 12),
        ServiceStatus(key: "agent", label: "AI agent", state: "up", summary: "Working", detail: "Beacon", checkedAt: now, latencyMs: nil),
        ServiceStatus(key: "pihole", label: "Pi-hole", state: "up", summary: "DNS up · blocking", detail: "Up 5 days (healthy)", checkedAt: now, latencyMs: nil),
        ServiceStatus(key: "minecraft", label: "Minecraft", state: "up", summary: "Online · 2/20 players", detail: "1.21.1", checkedAt: now, latencyMs: nil),
        ServiceStatus(key: "server", label: "Host metrics", state: "up", summary: "CPU 24% · RAM 48%", detail: nil, checkedAt: now, latencyMs: nil),
        ServiceStatus(key: "docker", label: "Docker", state: "up", summary: "Read-only monitor", detail: nil, checkedAt: now, latencyMs: nil)
    ]

    static let dockerPihole = DockerContainerInfo(
        name: "pihole",
        image: "pihole/pihole:2026.10.1",
        state: "running",
        status: "Up 5 days (healthy)",
        health: "healthy",
        cpuPercent: 0.42,
        memoryBytes: 39_000_000,
        memoryLimitBytes: 16_000_000_000,
        startedAt: now - 5 * 86_400,
        error: nil
    )

    static let server = ServerOverview(
        generatedAt: now,
        uptimeSeconds: 9.9 * 86_400,
        cpu: ServerCpu(
            percent: 24.0,
            perCore: [12, 28, 18, 22, 30, 14, 20, 25],
            load: [1.21, 1.02, 0.94],
            temperatureC: 51,
            model: "Intel(R) Core(TM) i5-9300H CPU @ 2.40GHz",
            cores: 8
        ),
        memory: ServerMemory(
            totalBytes: 16_230_904,
            usedBytes: 7_600_000_000,
            availableBytes: 8_200_000_000,
            percent: 48.0,
            swapTotalBytes: 12_599_292,
            swapUsedBytes: 1_203_328,
            swapPercent: 9.6
        ),
        gpu: ServerGpu(
            available: true,
            name: "NVIDIA GeForce GTX 1650",
            utilizationPercent: 12,
            temperatureC: 41,
            memoryUsedBytes: 536_870_912,
            memoryTotalBytes: 4_294_967_296,
            powerW: 8.4,
            error: nil
        ),
        disks: [
            DiskUsage(mount: "/", filesystem: "ext4", totalBytes: 236_000_000_000, usedBytes: 58_000_000_000, freeBytes: 167_000_000_000, percent: 26),
            DiskUsage(mount: "/mnt/storage_hdd", filesystem: "ext4", totalBytes: 983_000_000_000, usedBytes: 266_000_000, freeBytes: 974_000_000_000, percent: 0.1)
        ],
        network: NetworkThroughput(
            interface: "enp3s0",
            rxBytesPerSecond: 240_000,
            txBytesPerSecond: 96_000,
            rxBytesTotal: 9_186_168_928,
            txBytesTotal: 10_525_302_082
        ),
        docker: [dockerPihole],
        dockerAvailable: true,
        dockerError: nil,
        unavailable: []
    )

    static let pihole = PiholeStatus(
        available: true,
        online: true,
        blocking: "enabled",
        container: dockerPihole,
        queriesTotal: 35_933,
        queriesBlocked: 5_186,
        percentBlocked: 14.43,
        uniqueDomains: 5_232,
        queriesForwarded: 2_576,
        queriesCached: 28_076,
        topBlockedDomains: [
            DomainCount(name: "scribe.logs.roku.com", count: 3_526),
            DomainCount(name: "logs.netflix.com", count: 601),
            DomainCount(name: "end.scorecardresearch.com", count: 150)
        ],
        topClients: [
            DomainCount(name: "192.168.1.83", count: 12_030),
            DomainCount(name: "192.168.1.75", count: 7_087)
        ],
        upstreams: [
            UpstreamInfo(name: "one.one.one.one", address: "1.0.0.1:53", count: 1_664, responseAvgMs: 22.1),
            UpstreamInfo(name: "one.one.one.one", address: "1.1.1.1:53", count: 912, responseAvgMs: 14.5)
        ],
        generatedAt: now,
        error: nil
    )

    static let minecraft = MinecraftStatus(
        available: true,
        online: true,
        state: "running",
        version: "1.21.1",
        loader: "NeoForge 21.1.252",
        modsCount: 91,
        protocolNumber: 767,
        motd: "sussy pussy",
        playersOnline: 2,
        playersMax: 20,
        players: ["PorscheLegend23", "ecoeric"],
        uptimeSeconds: 3.4 * 86_400,
        pid: 34_408,
        cpuPercent: 12.4,
        memoryBytes: 9_780_000_000,
        tps: nil,
        mspt: nil,
        tickMetricsNote: "Tick metrics unavailable: no spark/TPS provider installed and RCON/query are disabled",
        recentErrors: [],
        recentEvents: ["PorscheLegend23 joined the game"],
        logUpdatedAt: now - 5,
        lastBackupAt: nil,
        backupNote: "No backup directory found in the server folder — no existing mechanism detected",
        controls: MinecraftControls(
            available: true,
            actions: ["stop", "restart"],
            stopMethod: "sigint",
            startMethod: nil,
            reason: nil
        ),
        generatedAt: now,
        error: nil
    )

    static let activity = ActivityFeed(
        unread: 2,
        items: [
            ActivityItem(
                id: "activity-1",
                kind: "milestone_completed",
                severity: "success",
                title: "Milestone 2: Native iOS foundation",
                body: "Design system, navigation and dashboard views are in place.",
                createdAt: now - 300,
                readAt: nil,
                payload: [:]
            ),
            ActivityItem(
                id: "activity-2",
                kind: "minecraft_online",
                severity: "success",
                title: "Minecraft server is online",
                body: "1.21.1 · 2 players",
                createdAt: now - 1_800,
                readAt: nil,
                payload: [:]
            )
        ]
    )

    static let milestones: [Milestone] = [
        Milestone(
            id: "milestone-2",
            seq: 2,
            title: "Native iOS foundation",
            summary: "SwiftUI project, design system and the home dashboard running against the live backend.",
            changes: [
                "Created the Xcode project with app, unit and snapshot test targets",
                "Added the Beacon design system (cards, pills, metric tiles)",
                "Implemented the pinned-TLS API client and Keychain token storage",
                "Home dashboard composed from a single /summary request"
            ],
            phase: "Phase 2",
            createdAt: now - 3_600,
            screenshots: [screenshot(0), screenshot(1), screenshot(2), screenshot(3)],
            expiredScreenshots: 0
        ),
        Milestone(
            id: "milestone-1",
            seq: 1,
            title: "Backend, agent integration and monitoring live",
            summary: "FastAPI service deployed with HTTPS, token auth, agent queue, milestone retention and real Pi-hole/Minecraft monitoring.",
            changes: [
                "FastAPI + SQLite service under systemd on port 8091",
                "Read-only Cherry Studio evidence and a push-based status snapshot",
                "Durable message queue with checkpoint delivery and a direct SIGINT interrupt",
                "Pi-hole v6 integration, Minecraft ping/log monitoring, host metrics"
            ],
            phase: "Phase 1",
            createdAt: now - 7 * 3_600,
            screenshots: [],
            expiredScreenshots: 4
        )
    ]

    static let dashboard = DashboardSummary(
        generatedAt: now,
        agent: agent,
        services: services,
        server: server,
        pihole: pihole,
        minecraft: minecraft,
        latestMilestone: milestones.first,
        activity: activity,
        dataAgeSeconds: 20
    )

    static let capabilities = Capabilities(
        agent: .init(
            bindingMode: "cherry-studio dsh runtime",
            configuredAgentId: "cc33efa9-6b9f-41f0-bf75-86dbc6e27096",
            statusSource: "agent snapshot + Cherry Studio SQLite (read-only) + /proc"
        ),
        messageDelivery: .init(mode: "checkpoint", maxMessageChars: 4000),
        interrupt: .init(modes: ["signal", "checkpoint"], signal: "SIGINT"),
        screenshots: .init(retentionDays: 7, sources: ["text", "api", "window", "file"], maxPerMilestone: 4),
        monitoring: .init(
            docker: true,
            dockerError: nil,
            gpu: true,
            gpuError: nil,
            cpuTemperature: true,
            minecraftTickMetrics: false,
            minecraftControlActions: ["stop", "restart"],
            pihole: true
        ),
        notifications: .init(
            inApp: true,
            push: false,
            pushNote: "APNs is an extension point, not implemented"
        )
    )
}
