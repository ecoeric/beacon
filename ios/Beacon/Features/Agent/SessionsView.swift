// SessionsView.swift
// Beacon
//
// Session picker and quick chat browser. The actual conversation UI lives in ChatView.swift;
// this list is used both as the full-screen Chat tab's switcher and as the Agent tab's quick
// browser sheet. Sending is supported for any existing session; creating a new chat still
// belongs to Cherry Studio.

import SwiftUI

struct SessionsView: View {
    /// When supplied, the list acts as a picker and dismisses after a selection. Otherwise the
    /// selected transcript is shown in a sheet (the Agent tab's quick browser).
    var onSelect: ((AgentSessionSummary) -> Void)? = nil

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
                                if let onSelect {
                                    onSelect(session)
                                    dismiss()
                                } else {
                                    selected = session
                                }
                            } label: {
                                row(session)
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    Text(onSelect == nil
                         ? "Tap a chat to open it. New chats are still created in Cherry Studio."
                         : "Choose a chat to open it.")
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
                ChatConversationView(session: session)
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
