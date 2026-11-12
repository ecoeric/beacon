// RootView.swift
// Beacon
//
// Native tab navigation. Polling follows the scene phase so the app never hammers the server
// while it is backgrounded, and refresh happens immediately when it comes back.

import SwiftUI

struct RootView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var selection: Tab = .dashboard

    enum Tab: Hashable {
        case dashboard
        case agent
        case progress
        case server
    }

    var body: some View {
        Group {
            if model.isConfigured {
                TabView(selection: $selection) {
                    DashboardView(onOpenAgent: { selection = .agent })
                        .tabItem { Label("Home", systemImage: "house") }
                        .tag(Tab.dashboard)

                    AgentView()
                        .tabItem { Label("Agent", systemImage: "sparkles") }
                        .badge(model.agent?.queue.pending ?? 0)
                        .tag(Tab.agent)

                    MilestonesView()
                        .tabItem { Label("Progress", systemImage: "square.grid.2x2") }
                        .tag(Tab.progress)

                    ServerView()
                        .tabItem { Label("Server", systemImage: "server.rack") }
                        .tag(Tab.server)
                }
                .tint(Theme.accent)
            } else {
                OnboardingView()
            }
        }
        .task { await model.bootstrap() }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active:
                model.startPolling()
                Task { await model.refresh(showSpinner: false) }
            case .background, .inactive:
                model.stopPolling()
            @unknown default:
                break
            }
        }
    }
}

#Preview {
    RootView()
        .environmentObject(AppModel.preview(summary: Fixtures.dashboard, milestones: Fixtures.milestones))
}
