// DashboardView.swift
// Beacon
//
// The home screen answers, at a glance: what is the agent doing, are the services well, how is
// the host, and what was the last milestone. Everything technical is one tap away.

import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var model: AppModel
    var onOpenAgent: () -> Void

    @State private var showSettings = false
    @State private var viewer: ViewerContext?

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
                    if let summary = model.summary {
                        agentCard(summary.agent)
                        servicesCard(summary.services)
                        hostCard(summary.server)
                        milestoneCard(summary)
                        activityCard(summary.activity)
                        footer
                    } else {
                        placeholder
                    }
                }
                .padding(Theme.screenPadding)
                .padding(.bottom, 28)
            }
            .beaconScreen()
            .refreshable {
                await model.refresh()
                await model.refreshMilestones()
            }
            .navigationTitle("Home")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .font(.system(size: 15, weight: .medium))
                    }
                    .accessibilityLabel("Settings")
                }
                ToolbarItem(placement: .topBarLeading) {
                    StatusPill(
                        text: model.connection.isOnline ? "Live" : "Offline",
                        tone: model.connection.isOnline ? .success : .danger,
                        symbol: model.connection.isOnline ? "dot.radiowaves.left.and.right" : "wifi.slash",
                        compact: true
                    )
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .sheet(item: $viewer) { context in
                ScreenshotViewer(milestoneTitle: context.milestoneTitle, screenshots: context.screenshots, startIndex: context.index)
            }
        }
    }

    // MARK: - Agent

    private func agentCard(_ agent: AgentStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 8) {
                StatusPill(text: agent.stateLabel, tone: agent.state.tone, symbol: agent.state.symbolName)
                if agent.isStale {
                    StatusPill(text: "stale", tone: .warning, symbol: "clock.badge.questionmark", compact: true)
                }
                Spacer()
                MetaText(text: Format.age(agent.updatedAt), symbol: "clock")
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(agent.project.isEmpty ? "No project reported" : agent.project)
                    .font(.beaconTitle)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
                if !agent.stage.isEmpty {
                    Text(agent.stage)
                        .font(.beaconCaption)
                        .foregroundStyle(Theme.accent)
                }
            }

            if !agent.activity.isEmpty {
                Text(agent.activity)
                    .font(.beaconBody)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !agent.lastMilestone.isEmpty || !agent.nextAction.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    if !agent.lastMilestone.isEmpty {
                        labelledLine(
                            label: "Last milestone",
                            value: agent.lastMilestone,
                            symbol: "checkmark.seal",
                            tone: .success
                        )
                    }
                    if !agent.nextAction.isEmpty {
                        labelledLine(
                            label: "Next",
                            value: agent.nextAction,
                            symbol: "arrow.forward.circle",
                            tone: .accent
                        )
                    }
                }
                .padding(12)
                .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
            }

            if !agent.blockers.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(agent.blockers.prefix(3), id: \.self) { blocker in
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "exclamationmark.octagon.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(Theme.warning)
                                .padding(.top, 2)
                            Text(blocker)
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            HStack(spacing: 10) {
                if agent.queue.pending > 0 {
                    StatusPill(text: "\(agent.queue.pending) queued", tone: .warning, symbol: "tray.full", compact: true)
                }
                if agent.session.turnRunning {
                    MetaText(text: "turn running", symbol: "bolt.fill")
                }
                Spacer()
                Button {
                    onOpenAgent()
                } label: {
                    HStack(spacing: 4) {
                        Text("Agent")
                        Image(systemName: "chevron.right")
                            .font(.system(size: 10, weight: .semibold))
                    }
                    .font(.beaconCaption)
                    .foregroundStyle(Theme.accent)
                }
                .buttonStyle(.plain)
            }
        }
        .beaconCard()
    }

    private func labelledLine(label: String, value: String, symbol: String, tone: Tone) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbol)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.colour(for: tone))
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 1) {
                Text(label.uppercased())
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
                    .tracking(0.5)
                Text(value)
                    .font(.beaconBody)
                    .foregroundStyle(.primary)
                    .lineLimit(2)
            }
        }
    }

    // MARK: - Services

    private func servicesCard(_ services: [ServiceStatus]) -> some View {
        let visible = services.filter { ["pihole", "minecraft", "server", "docker"].contains($0.key) }
        return VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Services", subtitle: "Pi-hole · Minecraft · host")
            ForEach(visible) { service in
                HStack(spacing: 10) {
                    Image(systemName: symbol(for: service.key))
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Theme.colour(for: service.tone))
                        .frame(width: 20)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(service.label)
                            .font(.beaconBody)
                            .foregroundStyle(.primary)
                        if let detail = service.detail, !detail.isEmpty {
                            Text(detail)
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    Spacer(minLength: 8)
                    Text(service.summary)
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.trailing)
                        .lineLimit(2)
                    StatusPill(text: service.state, tone: service.tone, compact: true)
                }
                if service.key != visible.last?.key {
                    DividerLine()
                }
            }
        }
        .beaconCard()
    }

    private func symbol(for key: String) -> String {
        switch key {
        case "pihole": return "shield.lefthalf.filled"
        case "minecraft": return "cube.fill"
        case "docker": return "shippingbox"
        case "server": return "cpu"
        case "agent": return "sparkles"
        default: return "circle"
        }
    }

    // MARK: - Host

    private func hostCard(_ server: ServerOverview) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(
                title: "Host",
                subtitle: server.uptimeSeconds.map { "up \(Format.duration($0))" }
            )
            LazyVGrid(columns: columns, spacing: 10) {
                MetricTile(
                    title: "CPU",
                    value: Format.percent(server.cpu.percent),
                    detail: server.cpu.temperatureC.map { "\(Format.celsius($0))" } ?? "no sensor",
                    fraction: (server.cpu.percent ?? 0) / 100,
                    tone: tone(for: server.cpu.percent)
                )
                MetricTile(
                    title: "Memory",
                    value: server.memory.map { Format.percent($0.percent) } ?? "—",
                    detail: server.memory.map { "\(Format.bytes($0.availableBytes)) free" },
                    fraction: (server.memory?.percent ?? 0) / 100,
                    tone: tone(for: server.memory?.percent)
                )
                MetricTile(
                    title: "GPU",
                    value: server.gpu.available ? Format.percent(server.gpu.utilizationPercent) : "—",
                    detail: server.gpu.available
                        ? server.gpu.temperatureC.map { Format.celsius($0) }
                        : server.gpu.error,
                    fraction: (server.gpu.utilizationPercent ?? 0) / 100,
                    tone: .accent
                )
                MetricTile(
                    title: "Disk",
                    value: Format.percent(server.disks.first?.percent),
                    detail: server.disks.first.map { "\(Format.bytes($0.freeBytes)) free · \($0.mount)" },
                    fraction: (server.disks.first?.percent ?? 0) / 100,
                    tone: (server.disks.first?.percent ?? 0) > 90 ? .danger : .success
                )
            }
            if let network = server.network {
                HStack(spacing: 14) {
                    MetaText(text: "↓ \(Format.rate(network.rxBytesPerSecond))", symbol: "arrow.down")
                    MetaText(text: "↑ \(Format.rate(network.txBytesPerSecond))", symbol: "arrow.up")
                    Spacer()
                    MetaText(text: network.interface, symbol: "network")
                }
            }
            if !server.unavailable.isEmpty {
                InlineNote(text: "Not readable on this host: " + server.unavailable.joined(separator: " · "))
            }
        }
        .beaconCard()
    }

    private func tone(for percent: Double?) -> Tone {
        guard let percent else { return .neutral }
        if percent > 90 { return .danger }
        if percent > 70 { return .warning }
        return .accent
    }

    // MARK: - Milestone

    @ViewBuilder
    private func milestoneCard(_ summary: DashboardSummary) -> some View {
        if let milestone = summary.latestMilestone {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    title: "Milestone #\(milestone.seq)",
                    subtitle: milestone.title,
                    actionTitle: nil,
                    action: nil
                )
                if !milestone.summary.isEmpty {
                    Text(milestone.summary)
                        .font(.beaconBody)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if milestone.screenshots.isEmpty {
                    EmptyState(
                        symbol: "photo.on.rectangle.angled",
                        title: "Screenshots expired",
                        message: "Images are kept for 7 days. The milestone summary stays available."
                    )
                } else {
                    LazyVGrid(columns: columns, spacing: 8) {
                        ForEach(Array(milestone.screenshots.prefix(4).enumerated()), id: \.element.id) { index, shot in
                            AsyncScreenshot(
                                id: shot.id,
                                caption: shot.caption,
                                height: 128,
                                loader: { id in try await model.screenshotData(id: id) }
                            )
                            .contentShape(Rectangle())
                            .onTapGesture {
                                viewer = ViewerContext(
                                    milestoneTitle: milestone.title,
                                    screenshots: milestone.screenshots,
                                    index: index
                                )
                            }
                        }
                    }
                }
                HStack {
                    MetaText(text: Format.dayAndTime(milestone.createdAt), symbol: "calendar")
                    Spacer()
                    if milestone.expiredScreenshots > 0 {
                        MetaText(text: "\(milestone.expiredScreenshots) expired", symbol: "clock.badge.xmark")
                    }
                }
            }
            .beaconCard()
        }
    }

    // MARK: - Activity

    private func activityCard(_ activity: ActivityFeed) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(
                title: "Activity",
                subtitle: activity.unread > 0 ? "\(activity.unread) unread" : "All caught up",
                actionTitle: activity.unread > 0 ? "Mark read" : nil,
                action: activity.unread > 0 ? { Task { await model.markAllActivityRead() } } : nil
            )
            if activity.items.isEmpty {
                InlineNote(text: "Service transitions and agent events appear here.")
            } else {
                ForEach(activity.items.prefix(3)) { item in
                    ActivityRow(item: item)
                    if item.id != activity.items.prefix(3).last?.id {
                        DividerLine()
                    }
                }
            }
        }
        .beaconCard()
    }

    private var footer: some View {
        VStack(spacing: 6) {
            HStack(spacing: 6) {
                Circle()
                    .fill(model.connection.isOnline ? Theme.success : Theme.danger)
                    .frame(width: 6, height: 6)
                Text("\(model.connection.label) · \(model.hostLabel)")
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
            }
            Text("\(model.freshnessText) · data ages are shown per card")
                .font(.beaconTiny)
                .foregroundStyle(Color.secondary.opacity(0.8))
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 4)
    }

    private var placeholder: some View {
        VStack(spacing: Theme.spacing) {
            LoadingCard(lines: 4)
            LoadingCard(lines: 3)
            LoadingCard(lines: 2)
            if !model.isRefreshing && !model.isConfigured {
                EmptyState(
                    symbol: "antenna.radiowaves.left.and.right.slash",
                    title: "Not connected",
                    message: "Open Settings to point Beacon at your server."
                )
            }
        }
    }
}

struct ViewerContext: Identifiable {
    let milestoneTitle: String
    let screenshots: [ScreenshotMeta]
    let index: Int
    var id: String { (screenshots.first?.id ?? "none") + "-\(index)" }
}
