// ServerView.swift
// Beacon
//
// Host metrics, Docker containers, Pi-hole and Minecraft. Technical detail lives in
// disclosure groups; destructive controls always go through an explicit confirmation.

import SwiftUI

struct ServerView: View {
    @EnvironmentObject private var model: AppModel

    @State private var showLogs = false
    @State private var pendingMinecraftAction: String?
    @State private var pendingBlockingValue: Bool?
    @State private var feedback: String?
    @State private var feedbackIsError = false
    @State private var showAdvanced = false

    private var columns: [GridItem] {
        [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Theme.spacing) {
                    if let error = model.errorMessage {
                        ErrorBanner(message: error) {
                            Task { await model.refresh() }
                        }
                    }
                    if let message = feedback {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: feedbackIsError ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                                .font(.system(size: 12))
                                .foregroundStyle(feedbackIsError ? Theme.warning : Theme.success)
                                .padding(.top, 1)
                            Text(message)
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                        .beaconCard(padding: 12)
                    }

                    if let server = model.server {
                        hostCard(server)
                        storageCard(server)
                        dockerCard(server)
                    } else {
                        LoadingCard(lines: 4)
                    }
                    if let pihole = model.pihole {
                        piholeCard(pihole)
                    }
                    if let minecraft = model.minecraft {
                        minecraftCard(minecraft)
                    }
                    advancedFooter
                }
                .padding(Theme.screenPadding)
                .padding(.bottom, 28)
            }
            .beaconScreen()
            .refreshable { await model.refresh() }
            .navigationTitle("Server")
            .sheet(isPresented: $showLogs) {
                MinecraftLogsSheet()
            }
            .confirmationDialog(
                minecraftDialogTitle,
                isPresented: Binding(
                    get: { pendingMinecraftAction != nil },
                    set: { if !$0 { pendingMinecraftAction = nil } }
                ),
                titleVisibility: .visible
            ) {
                if let action = pendingMinecraftAction {
                    Button(action == "stop" ? "Stop server" : action.capitalized) {
                        runMinecraft(action: action, force: false)
                    }
                    if action == "stop" {
                        Button("Force stop (players online)", role: .destructive) {
                            runMinecraft(action: action, force: true)
                        }
                    }
                    Button("Cancel", role: .cancel) { pendingMinecraftAction = nil }
                }
            } message: {
                Text("The server is shared: stopping it disconnects anyone playing. Beacon waits for a graceful shutdown and reports the result.")
            }
            .confirmationDialog(
                pendingBlockingValue == true ? "Enable DNS blocking?" : "Disable DNS blocking?",
                isPresented: Binding(
                    get: { pendingBlockingValue != nil },
                    set: { if !$0 { pendingBlockingValue = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button(pendingBlockingValue == true ? "Enable blocking" : "Disable blocking", role: .destructive) {
                    guard let value = pendingBlockingValue else { return }
                    Task {
                        let result = await model.togglePihole(enabled: value)
                        feedback = result.text
                        feedbackIsError = !result.success
                    }
                }
                Button("Cancel", role: .cancel) { pendingBlockingValue = nil }
            } message: {
                Text("This changes filtering for every device on the network.")
            }
        }
    }

    private var minecraftDialogTitle: String {
        switch pendingMinecraftAction {
        case "start": return "Start the Minecraft server?"
        case "stop": return "Stop the Minecraft server?"
        case "restart": return "Restart the Minecraft server?"
        default: return "Minecraft"
        }
    }

    private func runMinecraft(action: String, force: Bool) {
        Task {
            let result = await model.minecraftAction(action, force: force)
            feedback = result.text
            feedbackIsError = !result.success
            pendingMinecraftAction = nil
        }
    }

    // MARK: - Host

    private func hostCard(_ server: ServerOverview) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Host", subtitle: server.cpu.model)
            LazyVGrid(columns: columns, spacing: 10) {
                MetricTile(
                    title: "CPU",
                    value: Format.percent(server.cpu.percent),
                    detail: temperatureLine(server.cpu.temperatureC),
                    fraction: (server.cpu.percent ?? 0) / 100,
                    tone: loadTone(server.cpu.percent)
                )
                MetricTile(
                    title: "Memory",
                    value: server.memory.map { Format.percent($0.percent) } ?? "—",
                    detail: server.memory.map { "\(Format.bytes($0.usedBytes)) of \(Format.bytes($0.totalBytes))" },
                    fraction: (server.memory?.percent ?? 0) / 100,
                    tone: loadTone(server.memory?.percent)
                )
                MetricTile(
                    title: "GPU",
                    value: server.gpu.available ? Format.percent(server.gpu.utilizationPercent) : "—",
                    detail: server.gpu.available ? temperatureLine(server.gpu.temperatureC) : "unavailable",
                    fraction: (server.gpu.utilizationPercent ?? 0) / 100
                )
                MetricTile(
                    title: "Load (1m)",
                    value: server.cpu.load.first.map { String(format: "%.2f", $0) } ?? "—",
                    detail: "\(server.cpu.cores) threads",
                    fraction: min(1, (server.cpu.load.first ?? 0) / Double(max(server.cpu.cores, 1)))
                )
            }
            HStack(spacing: 14) {
                MetaText(text: "up \(Format.duration(server.uptimeSeconds))", symbol: "clock.arrow.circlepath")
                if let network = server.network {
                    MetaText(text: "↓ \(Format.rate(network.rxBytesPerSecond))", symbol: "arrow.down")
                    MetaText(text: "↑ \(Format.rate(network.txBytesPerSecond))", symbol: "arrow.up")
                }
                Spacer()
            }
            if !server.unavailable.isEmpty {
                InlineNote(text: "Unavailable: " + server.unavailable.joined(separator: " · "))
            }
            DisclosureGroup(isExpanded: $showAdvanced) {
                VStack(alignment: .leading, spacing: 4) {
                    if server.gpu.available {
                        KeyValueRow(label: "GPU", value: server.gpu.name ?? "—")
                        KeyValueRow(
                            label: "VRAM",
                            value: "\(Format.bytes(server.gpu.memoryUsedBytes)) / \(Format.bytes(server.gpu.memoryTotalBytes))"
                        )
                        KeyValueRow(label: "GPU power", value: Format.watts(server.gpu.powerW))
                    }
                    if let memory = server.memory {
                        KeyValueRow(
                            label: "Swap",
                            value: "\(Format.bytes(memory.swapUsedBytes)) / \(Format.bytes(memory.swapTotalBytes)) (\(Format.percent(memory.swapPercent)))"
                        )
                    }
                    if let network = server.network {
                        KeyValueRow(label: "Interface", value: network.interface, mono: true)
                        KeyValueRow(label: "Received", value: Format.bytes(network.rxBytesTotal))
                        KeyValueRow(label: "Sent", value: Format.bytes(network.txBytesTotal))
                    }
                }
                .padding(.top, 6)
            } label: {
                Text("Details")
                    .font(.beaconCaption)
                    .foregroundStyle(Theme.accent)
            }
        }
        .beaconCard()
    }

    private func temperatureLine(_ value: Double?) -> String? {
        value.map { Format.celsius($0) }
    }

    private func loadTone(_ percent: Double?) -> Tone {
        guard let percent else { return .neutral }
        if percent > 90 { return .danger }
        if percent > 70 { return .warning }
        return .accent
    }

    // MARK: - Storage & Docker

    private func storageCard(_ server: ServerOverview) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Storage")
            ForEach(server.disks) { disk in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(disk.mount)
                            .font(.beaconBody)
                            .foregroundStyle(.primary)
                        Text(disk.filesystem)
                            .font(.beaconTiny)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text("\(Format.bytes(disk.freeBytes)) free · \(Format.percent(disk.percent))")
                            .font(.beaconTiny)
                            .foregroundStyle(.secondary)
                    }
                    ProgressTrack(
                        fraction: disk.percent / 100,
                        tone: disk.percent > 90 ? .danger : (disk.percent > 75 ? .warning : .success)
                    )
                }
                .padding(.vertical, 2)
            }
        }
        .beaconCard()
    }

    private func dockerCard(_ server: ServerOverview) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(
                title: "Containers",
                subtitle: server.dockerAvailable ? "\(server.docker.count) running via read-only monitor" : "not readable"
            )
            if server.dockerAvailable {
                ForEach(server.docker) { container in
                    HStack(spacing: 10) {
                        Circle()
                            .fill(container.state == "running" ? Theme.success : Theme.neutral)
                            .frame(width: 7, height: 7)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(container.name)
                                .font(.beaconBody)
                            Text(container.image)
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(Format.percent(container.cpuPercent, digits: 2))
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                            Text(Format.bytes(container.memoryBytes))
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                        }
                        if let health = container.health {
                            StatusPill(text: health, tone: health == "healthy" ? .success : .warning, compact: true)
                        }
                    }
                    if container.id != server.docker.last?.id {
                        DividerLine()
                    }
                }
            } else {
                InlineNote(text: server.dockerError ?? "Docker metrics unavailable on this host.", symbol: "shippingbox")
            }
        }
        .beaconCard()
    }

    // MARK: - Pi-hole

    private func piholeCard(_ pihole: PiholeStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionHeader(title: "Pi-hole", subtitle: pihole.container?.image)
                Spacer()
                StatusPill(
                    text: pihole.available ? (pihole.isBlocking ? "blocking" : "not blocking") : "unreachable",
                    tone: pihole.available ? (pihole.isBlocking ? .success : .warning) : .danger,
                    symbol: "shield.lefthalf.filled"
                )
            }

            if !pihole.available {
                InlineNote(text: pihole.error ?? "The Pi-hole API is not reachable.", symbol: "exclamationmark.triangle")
            } else {
                LazyVGrid(columns: columns, spacing: 10) {
                    MetricTile(title: "Queries", value: Format.count(pihole.queriesTotal), detail: "\(Format.count(pihole.uniqueDomains)) domains")
                    MetricTile(
                        title: "Blocked",
                        value: Format.count(pihole.queriesBlocked),
                        detail: Format.percent(pihole.percentBlocked, digits: 1),
                        fraction: (pihole.percentBlocked ?? 0) / 100,
                        tone: .warning
                    )
                }
                if let container = pihole.container {
                    HStack(spacing: 8) {
                        MetaText(text: "container \(container.state)", symbol: "shippingbox")
                        if let health = container.health {
                            StatusPill(text: health, tone: health == "healthy" ? .success : .warning, compact: true)
                        }
                        Spacer()
                        MetaText(text: Format.age(pihole.generatedAt), symbol: "clock")
                    }
                }

                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 10) {
                        statList(title: "Top blocked domains", items: pihole.topBlockedDomains)
                        statList(title: "Top clients", items: pihole.topClients)
                        if !pihole.upstreams.isEmpty {
                            Text("UPSTREAMS")
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                                .tracking(0.5)
                            ForEach(pihole.upstreams) { upstream in
                                KeyValueRow(
                                    label: upstream.name,
                                    value: upstream.responseAvgMs.map { String(format: "%.1f ms · %@", $0, Format.count(upstream.count)) }
                                        ?? Format.count(upstream.count),
                                    mono: true
                                )
                            }
                        }
                    }
                    .padding(.top, 8)
                } label: {
                    Text("Statistics")
                        .font(.beaconCaption)
                        .foregroundStyle(Theme.accent)
                }

                Button {
                    pendingBlockingValue = !pihole.isBlocking
                } label: {
                    Label(
                        pihole.isBlocking ? "Disable blocking" : "Enable blocking",
                        systemImage: "shield.slash"
                    )
                }
                .buttonStyle(BeaconSecondaryButtonStyle())
                .disabled(model.isPerformingAction)
            }
        }
        .beaconCard()
    }

    private func statList(title: String, items: [DomainCount]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
                .tracking(0.5)
            if items.isEmpty {
                Text("No data")
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(items.prefix(5)) { item in
                    HStack {
                        Text(item.name)
                            .font(.beaconTiny)
                            .lineLimit(1)
                        Spacer()
                        Text(Format.count(item.count))
                            .font(.beaconTiny)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                }
            }
        }
    }

    // MARK: - Minecraft

    private func minecraftCard(_ minecraft: MinecraftStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionHeader(title: "Minecraft", subtitle: minecraft.version.map { "NeoForge · \($0)" })
                Spacer()
                StatusPill(
                    text: minecraft.state,
                    tone: minecraft.isRunning ? .success : .danger,
                    symbol: minecraft.isRunning ? "cube.fill" : "cube.transparent"
                )
            }

            if minecraft.isRunning {
                LazyVGrid(columns: columns, spacing: 10) {
                    MetricTile(
                        title: "Players",
                        value: "\(minecraft.playersOnline ?? 0)/\(minecraft.playersMax ?? 0)",
                        detail: minecraft.players.isEmpty ? "none connected" : minecraft.players.joined(separator: ", ")
                    )
                    MetricTile(
                        title: "Uptime",
                        value: Format.duration(minecraft.uptimeSeconds),
                        detail: minecraft.pid.map { "pid \($0)" }
                    )
                    MetricTile(
                        title: "CPU",
                        value: Format.percent(minecraft.cpuPercent, digits: 1),
                        fraction: (minecraft.cpuPercent ?? 0) / 100
                    )
                    MetricTile(
                        title: "Memory",
                        value: Format.bytes(minecraft.memoryBytes),
                        detail: "resident"
                    )
                }
                if let motd = minecraft.motd, !motd.isEmpty {
                    KeyValueRow(label: "MOTD", value: motd)
                }
            } else {
                InlineNote(text: minecraft.error ?? "The server is not running.", symbol: "cube.transparent")
            }

            if let note = minecraft.tickMetricsNote {
                InlineNote(text: note, symbol: "gauge.with.dots.needle.0percent")
            }
            if let backup = minecraft.lastBackupAt {
                KeyValueRow(label: "Last backup", value: Format.age(backup))
            } else if let backupNote = minecraft.backupNote {
                InlineNote(text: backupNote, symbol: "externaldrive.badge.xmark")
            }
            if !minecraft.recentErrors.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    Text("RECENT ERRORS")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                        .tracking(0.5)
                    ForEach(minecraft.recentErrors.prefix(2), id: \.self) { line in
                        Text(line)
                            .font(.beaconMono)
                            .foregroundStyle(Theme.warning)
                            .lineLimit(2)
                    }
                }
            }

            HStack(spacing: 10) {
                if minecraft.controls.actions.contains("start") {
                    Button("Start") { pendingMinecraftAction = "start" }
                        .buttonStyle(BeaconSecondaryButtonStyle())
                }
                if minecraft.controls.actions.contains("stop") {
                    Button("Stop") { pendingMinecraftAction = "stop" }
                        .buttonStyle(BeaconDestructiveButtonStyle())
                }
                if minecraft.controls.actions.contains("restart") {
                    Button("Restart") { pendingMinecraftAction = "restart" }
                        .buttonStyle(BeaconSecondaryButtonStyle())
                }
                Spacer()
                Button {
                    showLogs = true
                } label: {
                    Label("Logs", systemImage: "doc.text.magnifyingglass")
                        .font(.beaconCaption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Theme.accent)
            }
            if !minecraft.controls.available {
                InlineNote(
                    text: minecraft.controls.reason ?? "Controls are not available for this instance.",
                    symbol: "lock"
                )
            } else if let stopMethod = minecraft.controls.stopMethod {
                MetaText(text: "stop via \(stopMethod)", symbol: "terminal")
            }
        }
        .beaconCard()
    }

    private var advancedFooter: some View {
        VStack(spacing: 6) {
            if let capabilities = model.capabilities {
                Text("Monitoring: docker \(capabilities.monitoring.docker ? "on" : "off") · gpu \(capabilities.monitoring.gpu ? "on" : "off") · pihole \(capabilities.monitoring.pihole ? "on" : "off")")
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
                Text(capabilities.notifications.pushNote)
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            Text("Metrics come straight from /proc, sensors, nvidia-smi, the Docker read-only helper, the Pi-hole v6 API and the Minecraft server-list ping.")
                .font(.beaconTiny)
                .foregroundStyle(.secondary.opacity(0.85))
                .multilineTextAlignment(.center)
        }
        .padding(.top, 6)
    }
}

// MARK: - Minecraft logs sheet

struct MinecraftLogsSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var logs: MinecraftLogs?
    @State private var errorText: String?
    @State private var loading = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if loading {
                        ProgressView().padding(.top, 20)
                    } else if let errorText {
                        ErrorBanner(message: errorText)
                    } else if let logs {
                        if logs.tickWarnings > 0 {
                            InlineNote(text: "\(logs.tickWarnings) tick-warning line(s) in the log tail.", symbol: "gauge.with.dots.needle.0percent")
                        }
                        Text(logs.lines.suffix(120).joined(separator: "\n"))
                            .font(.system(size: 10, weight: .regular, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
                .padding(Theme.screenPadding)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .beaconScreen()
            .navigationTitle("latest.log")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .task {
            do {
                logs = try await model.minecraftLogs()
            } catch {
                errorText = error.localizedDescription
            }
            loading = false
        }
    }
}
