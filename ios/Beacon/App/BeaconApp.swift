// BeaconApp.swift
// Beacon

import SwiftUI

@main
@MainActor
struct BeaconApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .preferredColorScheme(nil)
        }
    }
}
