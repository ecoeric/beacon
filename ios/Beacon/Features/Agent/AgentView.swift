// AgentView.swift
// Beacon
//
// The compact interaction panel: status card, composer, recent messages, and a separate
// interrupt action. Deliberately not a chat app — no transcript, no bubbles, no streaming.

import SwiftUI

struct AgentView: View {
    @EnvironmentObject private var model: AppModel

    @State private var draft = ""
    @State private var showStatus = false
    @State private var showInterrupt = false
    @State private var feedback: Feedback?
    @FocusState private var composerFocused: Bool

    private struct Feedback: Identifiable {
        let id = UUID()
        let text: String
        let success: Bool
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
                    if let agent = model.agent {
                        statusCard(agent)
                        composerCard(agent)
                        messagesCard(agent)
                        interruptCard(agent)
                    } else {
                        LoadingCard(lines: 4)
                        LoadingCard(lines: 3)
                    }
                }
                .padding(Theme.screenPadding)
                .padding(.bottom, 28)
            }
            .beaconScreen()
            .scrollDismissesKeyboard(.interactively)
            .refreshable { await model.refresh() }
            .navigationTitle("Agent")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showStatus = true
                        Task { await model.loadStatusSummary() }
                    } label: {
                        Label("Status", systemImage: "doc.text.magnifyingglass")
                            .labelStyle(.titleAndIcon)
                            .font(.beaconCaption)
                    }
                    .accessibilityHint("Read-only summary of what the agent is doing")
                }
            }
            .sheet(isPresented: $showStatus) {
                StatusSheet()
            }
            .sheet(isPresented: $showInterrupt) {
                InterruptSheet { result in
                    feedback = Feedback(text: result.text, success: result.success)
                }
            }
        }
    }

    // MARK: - Status card

    private func statusCard(_ agent: AgentStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                StatusPill(text: agent.stateLabel, tone: agent.state.tone, symbol: agent.state.symbolName)
                if agent.isStale {
                    StatusPill(text: "stale", tone: .warning, symbol: "clock.badge.questionmark", compact: true)
                }
                Spacer()
                MetaText(text: Format.age(agent.updatedAt), symbol: "clock")
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(agent.project.isEmpty ? "No project reported" : agent.project)
                    .font(.beaconTitle)
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

            VStack(spacing: 0) {
                if !agent.lastMilestone.isEmpty {
                    KeyValueRow(label: "Last milestone", value: agent.lastMilestone)
                    DividerLine()
                }
                KeyValueRow(label: "Next action", value: agent.nextAction.isEmpty ? "—" : agent.nextAction)
                DividerLine()
                KeyValueRow(
                    label: "Queue",
                    value: "\(agent.queue.pending) queued · \(agent.queue.delivered) delivered",
                    valueTone: agent.queue.pending > 0 ? .warning : nil
                )
                if let interrupt = agent.latestInterrupt {
                    DividerLine()
                    KeyValueRow(
                        label: "Last interrupt",
                        value: "\(interrupt.mode) · \(interrupt.status) · \(Format.age(interrupt.requestedAt))",
                        valueTone: interrupt.status == "acknowledged" ? .neutral : .warning
                    )
                }
            }

            if !agent.blockers.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("BLOCKERS")
                        .font(.beaconTiny)
                        .tracking(0.5)
                        .foregroundStyle(.secondary)
                    ForEach(agent.blockers.prefix(4), id: \.self) { blocker in
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

            DisclosureGroup {
                VStack(alignment: .leading, spacing: 6) {
                    if let sessionId = agent.session.id {
                        KeyValueRow(label: "Session", value: String(sessionId.prefix(8)), mono: true)
                    }
                    KeyValueRow(
                        label: "Runtime",
                        value: agent.session.runtimePid.map { "pid \($0)" } ?? "not running",
                        valueTone: agent.session.runtimeAlive ? .success : .danger
                    )
                    KeyValueRow(
                        label: "Last activity",
                        value: agent.session.lastActivityKind ?? "—"
                    )
                    DividerLine()
                    ForEach(agent.evidence) { item in
                        VStack(alignment: .leading, spacing: 1) {
                            Text(item.source)
                                .font(.beaconTiny)
                                .foregroundStyle(.secondary)
                            Text(item.detail)
                                .font(.beaconTiny)
                                .foregroundStyle(.primary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(.vertical, 1)
                    }
                    ForEach(agent.notes, id: \.self) { note in
                        InlineNote(text: note)
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

    // MARK: - Composer

    private func composerCard(_ agent: AgentStatus) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(
                title: "Send to the agent",
                subtitle: "Queued; delivered at the agent's next safe checkpoint"
            )

            TextField("A suggestion, correction or extra requirement…", text: $draft, axis: .vertical)
                .font(.beaconBody)
                .lineLimit(2...6)
                .focused($composerFocused)
                .padding(12)
                .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
                .onChange(of: draft) { _, value in
                    if value.count > 4000 {
                        draft = String(value.prefix(4000))
                    }
                }

            HStack(spacing: 10) {
                Button {
                    submitSuggestion()
                } label: {
                    Text("Send")
                        .frame(minWidth: 64)
                }
                .buttonStyle(BeaconPrimaryButtonStyle())
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isPerformingAction)

                Button {
                    submitContinue()
                } label: {
                    Text("Continue")
                }
                .buttonStyle(BeaconSecondaryButtonStyle())
                .disabled(model.isPerformingAction)

                Spacer()

                if model.isPerformingAction {
                    ProgressView().controlSize(.small)
                } else {
                    Text("\(draft.count)/4000")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }
            }

            if let feedback {
                HStack(alignment: .top, spacing: 7) {
                    Image(systemName: feedback.success ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(feedback.success ? Theme.success : Theme.warning)
                        .padding(.top, 1)
                    Text(feedback.text)
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            InlineNote(
                text: "Messages never interrupt the current operation: they stay pending until the agent asks for its next checkpoint.",
                symbol: "tray.and.arrow.down"
            )

            if agent.state == .disconnected {
                InlineNote(
                    text: "The agent runtime is not running right now. Messages stay queued and are delivered when it comes back.",
                    symbol: "wifi.slash"
                )
            }
        }
        .beaconCard()
    }

    private func submitSuggestion() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        Task {
            let result = await model.sendSuggestion(text)
            feedback = Feedback(text: result.text, success: result.success)
            if result.success {
                draft = ""
                composerFocused = false
            }
        }
    }

    private func submitContinue() {
        let note = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            let result = await model.continueWork(note: note.isEmpty ? nil : note)
            feedback = Feedback(text: result.text, success: result.success)
            if result.success {
                draft = ""
                composerFocused = false
            }
        }
    }

    // MARK: - Messages

    private func messagesCard(_ agent: AgentStatus) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(
                title: "Recent messages",
                subtitle: model.messages.isEmpty ? "Nothing exchanged yet" : "\(model.messages.count) recent"
            )
            if model.messages.isEmpty {
                InlineNote(text: "Suggestions and Continue requests you send show up here with their delivery state.")
            } else {
                ForEach(model.messages) { message in
                    messageRow(message)
                    if message.id != model.messages.last?.id {
                        DividerLine()
                    }
                }
            }
        }
        .beaconCard()
    }

    private func messageRow(_ message: AgentMessage) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                StatusPill(text: message.kind.title, tone: message.kind == .continue ? .accent : .neutral, compact: true)
                StatusPill(text: message.status.title, tone: message.status.tone, compact: true)
                Spacer()
                Text(Format.age(message.createdAt))
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
                if message.status == .pending {
                    Button("Cancel") {
                        Task { await model.cancelMessage(id: message.id) }
                    }
                    .font(.beaconTiny)
                    .foregroundStyle(Theme.danger)
                    .buttonStyle(.plain)
                }
            }
            Text(message.body)
                .font(.beaconBody)
                .foregroundStyle(.primary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            if let note = message.ackNote ?? message.processedNote, !note.isEmpty {
                Text("Agent: \(note)")
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Interrupt

    private func interruptCard(_ agent: AgentStatus) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Interrupt", subtitle: "Stops the running turn out of band")
            Text("Interrupt signals the agent's execution system directly. It does not enter the message queue, it does not wait for a checkpoint, and it never rewrites files — the agent stops at its safest practical point and reports back.")
                .font(.beaconBody)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                Button {
                    showInterrupt = true
                } label: {
                    Label("Interrupt agent", systemImage: "stop.circle")
                }
                .buttonStyle(BeaconDestructiveButtonStyle())
                .disabled(model.isPerformingAction)
                Spacer()
                if agent.state == .disconnected {
                    MetaText(text: "no live runtime", symbol: "wifi.slash")
                }
            }
        }
        .beaconCard()
    }
}

// MARK: - Status sheet

struct StatusSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if model.isStatusLoading {
                        HStack(spacing: 10) {
                            ProgressView()
                            Text("Reading the latest snapshot…")
                                .font(.beaconBody)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.top, 8)
                    } else if let status = model.statusSummary {
                        StatusPill(text: status.state.title, tone: status.state.tone, symbol: status.state.symbolName)
                        Text(status.summary)
                            .font(.system(size: 19, weight: .regular))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                        VStack(alignment: .leading, spacing: 6) {
                            HStack(spacing: 8) {
                                MetaText(text: Format.age(status.generatedAt), symbol: "clock")
                                if status.isStale {
                                    StatusPill(text: "stale data", tone: .warning, compact: true)
                                }
                            }
                            InlineNote(
                                text: "Composed from the structured status snapshot on the server. No prompt was sent, no inference ran, and the agent's conversation was not touched.",
                                symbol: "lock.shield"
                            )
                            if !status.basedOn.isEmpty {
                                Text("Sources: " + status.basedOn.joined(separator: ", "))
                                    .font(.beaconTiny)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.top, 4)
                    } else {
                        EmptyState(
                            symbol: "doc.questionmark",
                            title: "No status available",
                            message: "The server could not compose a summary yet."
                        )
                    }
                }
                .padding(Theme.screenPadding)
            }
            .beaconScreen()
            .navigationTitle("Status")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task { await model.loadStatusSummary() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(model.isStatusLoading)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

// MARK: - Interrupt sheet

struct InterruptSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    let onFinished: (AppModel.MessageFeedback) -> Void

    @State private var mode = "signal"
    @State private var reason = ""
    @State private var working = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Mode", selection: $mode) {
                        Text("Signal now").tag("signal")
                        Text("At next checkpoint").tag("checkpoint")
                    }
                    .pickerStyle(.segmented)
                } header: {
                    Text("How")
                } footer: {
                    Text(mode == "signal"
                         ? "Sends SIGINT to the agent runtime process immediately. The session journal keeps its work, and the agent reports an interrupted state."
                         : "Records a cooperative interrupt that the agent consumes at its next safe checkpoint. Nothing is appended to its conversation.")
                }
                Section("Reason (optional)") {
                    TextField("Why are you interrupting?", text: $reason, axis: .vertical)
                        .lineLimit(2...5)
                }
                Section {
                    Button(role: .destructive) {
                        working = true
                        Task {
                            let result = await model.interruptAgent(mode: mode, reason: reason)
                            working = false
                            onFinished(result)
                            if result.success { dismiss() }
                        }
                    } label: {
                        HStack {
                            if working { ProgressView().controlSize(.small) }
                            Text(working ? "Interrupting…" : "Confirm interrupt")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .disabled(working)
                } footer: {
                    Text("The interrupt bypasses the message queue entirely. Queued messages stay queued.")
                }
            }
            .navigationTitle("Interrupt agent")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
