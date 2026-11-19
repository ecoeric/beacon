// ChatView.swift
// Beacon
//
// Full-screen agent chat. Sessions are selected from a sheet; the selected transcript polls for
// new user/assistant text and the composer sends a normal user turn through Beacon's writeable
// chat endpoint. This is intentionally a conversation UI, not a log viewer.

import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var model: AppModel
    @State private var session: AgentSessionSummary?
    @State private var showSessions = false
    @State private var loading = true

    var body: some View {
        NavigationStack {
            Group {
                if let session {
                    ChatConversationView(session: session, onSwitch: { showSessions = true })
                } else if loading {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if model.sessions.isEmpty {
                    EmptyState(
                        symbol: "bubble.left.and.bubble.right",
                        title: "No agent chats",
                        message: "Cherry Studio sessions for the configured agent appear here."
                    )
                    .beaconCard()
                    .padding(Theme.screenPadding)
                } else {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .beaconScreen()
            .navigationTitle(session.map { $0.name.isEmpty ? "Chat" : $0.name } ?? "Chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSessions = true
                    } label: {
                        Image(systemName: "list.bullet")
                    }
                    .accessibilityLabel("Switch chat")
                }
            }
            .sheet(isPresented: $showSessions) {
                SessionsView(onSelect: { selected in
                    session = selected
                })
            }
            .task {
                await model.loadSessions()
                if session == nil {
                    session = preferredSession(in: model.sessions)
                }
                loading = false
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(12))
                    if Task.isCancelled { return }
                    await model.loadSessions()
                    if session == nil {
                        session = preferredSession(in: model.sessions)
                    }
                }
            }
            .onChange(of: model.agent?.session.id) { _, _ in
                if session == nil {
                    session = preferredSession(in: model.sessions)
                }
            }
        }
    }

    private func preferredSession(in sessions: [AgentSessionSummary]) -> AgentSessionSummary? {
        if let current = model.agent?.session.id,
           let match = sessions.first(where: { $0.id == current }) {
            return match
        }
        return sessions.first
    }
}

struct ChatConversationView: View {
    let session: AgentSessionSummary
    var onSwitch: (() -> Void)? = nil

    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var messages: [AgentChatMessage] = []
    @State private var loading = true
    @State private var error: String?
    @State private var draft = ""
    @State private var feedback: String?
    @State private var sending = false

    private var isCurrentSession: Bool {
        if let current = model.agent?.session.id { return current == session.id }
        return model.sessions.first?.id == session.id
    }

    private var isWorking: Bool {
        sending || (isCurrentSession && model.agent?.session.turnRunning == true)
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if loading {
                            LoadingCard(lines: 5)
                        } else if let error {
                            ErrorBanner(message: error) {
                                Task { await load() }
                            }
                        } else if messages.isEmpty {
                            EmptyState(
                                symbol: "text.bubble",
                                title: "Start the conversation",
                                message: "Send a message below. It becomes a normal user turn in this Cherry Studio chat."
                            )
                            .beaconCard()
                        } else {
                            ForEach(messages.indices, id: \.self) { index in
                                let message = messages[index]
                                if showDayHeader(at: index) {
                                    dayHeader(message.createdAt)
                                }
                                ChatBubble(message: message)
                                    .id(message.id)
                            }
                        }

                        if isWorking {
                            HStack(spacing: 8) {
                                ProgressView()
                                Text(sending ? "Sending…" : "Agent is working…")
                                    .font(.beaconTiny)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 4)
                        }

                        Color.clear
                            .frame(height: 1)
                            .id("chat-bottom")
                    }
                    .padding(.horizontal, Theme.screenPadding)
                    .padding(.top, 12)
                    .padding(.bottom, 16)
                }
                .refreshable { await load(showLoading: false) }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: messages.count) { _, _ in
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo("chat-bottom", anchor: .bottom)
                    }
                }
                .onAppear {
                    proxy.scrollTo("chat-bottom", anchor: .bottom)
                }
            }

            DividerLine()
            composer
        }
        .beaconScreen()
        .navigationTitle(session.name.isEmpty ? "Chat" : session.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if let onSwitch {
                    Button(action: onSwitch) {
                        Image(systemName: "list.bullet")
                    }
                    .accessibilityLabel("Switch chat")
                } else {
                    Button("Done") { dismiss() }
                }
            }
        }
        .task(id: session.id) {
            messages = []
            loading = true
            await load()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                if Task.isCancelled { return }
                await load(showLoading: false)
            }
        }
    }

    private var composerPlaceholder: String {
        isCurrentSession ? "Message the active agent…" : "Message this agent…"
    }

    @ViewBuilder
    private var composer: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField(composerPlaceholder, text: $draft, axis: .vertical)
                    .font(.beaconBody)
                    .lineLimit(1...5)
                    .padding(.horizontal, 11)
                    .padding(.vertical, 9)
                    .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 31))
                }
                .buttonStyle(.plain)
                .foregroundStyle(Theme.accent)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sending)
                .opacity(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sending ? 0.4 : 1)
            }

            Text(feedback ?? (isCurrentSession
                ? "Sends to the active agent chat."
                : "Queues a turn here; Cherry dispatches it when it next checks this chat."))
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(.horizontal, Theme.screenPadding)
        .padding(.vertical, 8)
        .background(Theme.surface)
    }

    private func load(showLoading: Bool = true) async {
        if showLoading { loading = true }
        error = nil
        do {
            let loaded = try await model.sessionMessages(sessionId: session.id)
            messages = loaded
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
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
                try? await Task.sleep(for: .milliseconds(650))
                await load(showLoading: false)
            }
            feedback = result.text
            sending = false
        }
    }

    private func showDayHeader(at index: Int) -> Bool {
        guard index > 0 else { return true }
        return !Calendar.current.isDate(
            Date(timeIntervalSince1970: messages[index].createdAt),
            inSameDayAs: Date(timeIntervalSince1970: messages[index - 1].createdAt)
        )
    }

    private func dayHeader(_ timestamp: Double) -> some View {
        Text(Format.chatDay(timestamp))
            .font(.beaconTiny)
            .foregroundStyle(.tertiary)
            .frame(maxWidth: .infinity)
            .padding(.top, 2)
    }
}

private struct ChatBubble: View {
    let message: AgentChatMessage

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if isUser { Spacer(minLength: 42) }

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
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                    .background(
                        isUser ? Theme.accent.opacity(0.18) : Theme.surfaceElevated,
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                    )
            }

            if !isUser { Spacer(minLength: 42) }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}
