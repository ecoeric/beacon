// SessionsView.swift
// Beacon
//
// Read-only browser for Cherry Studio agent sessions and their visible transcript text.
// Beacon never writes to the Cherry Studio database and cannot create a new chat; that stays
// in Cherry Studio. This screen exists so the current and previous agent conversations can be
// inspected from the phone.

import SwiftUI

struct SessionsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var selected: AgentSessionSummary?
    @State private var loading = true

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 10) {
                    if loading {
                        LoadingCard(lines: 4)
                    } else if model.sessions.isEmpty {
                        EmptyState(
                            symbol: "bubble.left.and.bubble.right",
                            title: "No agent chats",
                            message: "Cherry Studio sessions for the configured agent appear here."
                        )
                        .beaconCard()
                    } else {
                        ForEach(model.sessions) { session in
                            Button {
                                selected = session
                            } label: {
                                row(session)
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    Text("Read-only browser. Create new chats in Cherry Studio; Beacon does not write to its database.")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.top, 4)
                }
                .padding(Theme.screenPadding)
                .padding(.bottom, 20)
            }
            .beaconScreen()
            .navigationTitle("Chats")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .refreshable { await model.loadSessions() }
            .task {
                await model.loadSessions()
                loading = false
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(10))
                    if Task.isCancelled { return }
                    await model.loadSessions()
                }
            }
            .sheet(item: $selected) { session in
                SessionTranscriptView(session: session)
            }
        }
    }

    private func row(_ session: AgentSessionSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(session.name.isEmpty ? "Untitled session" : session.name)
                    .font(.beaconHeadline)
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                if session.id == model.agent?.session.id {
                    StatusPill(text: "CURRENT", tone: .accent, compact: true)
                }
            }
            HStack(spacing: 10) {
                if let agent = session.agentName, !agent.isEmpty {
                    MetaText(text: agent, symbol: "cpu")
                }
                MetaText(text: Format.age(session.lastActivityAt), symbol: "clock")
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .beaconCard()
    }
}

struct SessionTranscriptView: View {
    let session: AgentSessionSummary

    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var messages: [AgentChatMessage] = []
    @State private var loading = true
    @State private var error: String?
    @State private var draft = ""
    @State private var feedback: String?
    @State private var sending = false

    private var isCurrentSession: Bool {
        if let current = model.agent?.session.id {
            return session.id == current
        }
        return model.sessions.first?.id == session.id
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if loading {
                            LoadingCard(lines: 5)
                        } else if let error {
                            ErrorBanner(message: error) {
                                Task { await load() }
                            }
                        } else if messages.isEmpty {
                            EmptyState(
                                symbol: "text.bubble",
                                title: "No visible messages",
                                message: "This session has no user or assistant text yet."
                            )
                            .beaconCard()
                        } else {
                            ForEach(messages) { message in
                                messageRow(message)
                            }
                        }
                    }
                    .padding(Theme.screenPadding)
                    .padding(.bottom, 20)
                }
                .refreshable { await load() }

                DividerLine()
                composer
            }
            .beaconScreen()
            .navigationTitle(session.name.isEmpty ? "Chat" : session.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task {
                await load()
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(5))
                    if Task.isCancelled { return }
                    await load(showLoading: false)
                }
            }
        }
    }

    private func load(showLoading: Bool = true) async {
        if showLoading { loading = true }
        error = nil
        do {
            messages = try await model.sessionMessages(sessionId: session.id)
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }

    @ViewBuilder
    private var composer: some View {
        if isCurrentSession {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    TextField("Message the active agent…", text: $draft, axis: .vertical)
                        .font(.beaconBody)
                        .lineLimit(1...4)
                        .padding(9)
                        .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    Button {
                        send()
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 28))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Theme.accent)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sending)
                    .opacity(sending ? 0.45 : 1)
                }
                Text(feedback ?? "Sends as a normal user message to the active agent.")
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, Theme.screenPadding)
            .padding(.vertical, 8)
            .background(Theme.surface)
        } else {
            Text("Read-only session. Open the current chat to send a message.")
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(10)
                .background(Theme.surface)
        }
    }

    private func send() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !sending else { return }
        sending = true
        feedback = "Sending…"
        Task {
            let result = await model.sendChatMessage(sessionId: session.id, text: text)
            if result.success {
                draft = ""
                try? await Task.sleep(for: .milliseconds(700))
                await load(showLoading: false)
            }
            feedback = result.text
            sending = false
        }
    }

    private func messageRow(_ message: AgentChatMessage) -> some View {
        let isUser = message.role == "user"
        return HStack {
            if isUser { Spacer(minLength: 28) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(isUser ? "You" : (message.model ?? "Agent"))
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                    Text(Format.age(message.createdAt))
                        .font(.beaconTiny)
                        .foregroundStyle(.tertiary)
                }
                Text(message.text.isEmpty ? "—" : message.text)
                    .font(.beaconBody)
                    .foregroundStyle(.primary)
                    .multilineTextAlignment(isUser ? .trailing : .leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(10)
                    .background(
                        isUser ? Theme.accent.opacity(0.16) : Theme.surfaceElevated,
                        in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous)
                    )
            }
            if !isUser { Spacer(minLength: 28) }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}
