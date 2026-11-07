// SettingsView.swift
// Beacon
//
// Deliberately plain: a native Form with the few things that matter — where the server is,
// what the token can do, and what the backend can actually read from this host.

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var showDisconnect = false
    @State private var testing = false
    @State private var testResult: String?
    @State private var testSucceeded = false

    private var tokenHint: String {
        guard let token = AppSettings.shared.token, token.count > 6 else { return "not stored" }
        return "…" + token.suffix(4)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Address", value: model.hostLabel)
                    LabeledContent("Connection", value: model.connection.label)
                    Button {
                        testConnection()
                    } label: {
                        HStack {
                            Text(testing ? "Testing…" : "Test connection")
                            Spacer()
                            if testing { ProgressView().controlSize(.small) }
                        }
                    }
                    .disabled(testing)
                    if let testResult {
                        Text(testResult)
                            .font(.beaconTiny)
                            .foregroundStyle(testSucceeded ? Theme.success : Theme.warning)
                    }
                } header: {
                    Text("Server")
                } footer: {
                    Text("Address and token are configured at first launch. Disconnect to change them.")
                }

                Section("Access") {
                    LabeledContent("Token", value: model.identityName ?? "unknown")
                    LabeledContent("Token id", value: tokenHint)
                    LabeledContent("Scopes", value: model.capabilities == nil ? "read, action, admin" : "read · action · admin")
                    LabeledContent("Certificate", value: AppSettings.shared.spkiPin == nil ? "private CA only" : "CA + SPKI pin")
                    Text("Traffic is validated against the private Beacon CA bundled in this app. The token and pin live in the iOS Keychain and are never sent anywhere except your server.")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }

                if let capabilities = model.capabilities {
                    Section("Backend") {
                        LabeledContent("Agent binding", value: capabilities.agent.bindingMode)
                        if let agentId = capabilities.agent.configuredAgentId {
                            LabeledContent("Agent id", value: String(agentId.prefix(8)))
                        }
                        LabeledContent("Status source", value: capabilities.agent.statusSource)
                        LabeledContent("Message delivery", value: capabilities.messageDelivery.mode)
                        LabeledContent("Interrupt modes", value: capabilities.interrupt.modes.joined(separator: ", "))
                        LabeledContent("Screenshot retention", value: "\(capabilities.screenshots.retentionDays) days")
                        LabeledContent("Screenshot sources", value: capabilities.screenshots.sources.joined(separator: ", "))
                        LabeledContent("Docker metrics", value: capabilities.monitoring.docker ? "available" : "unavailable")
                        LabeledContent("GPU metrics", value: capabilities.monitoring.gpu ? "available" : "unavailable")
                        LabeledContent("CPU temperature", value: capabilities.monitoring.cpuTemperature ? "available" : "unavailable")
                        LabeledContent("Pi-hole API", value: capabilities.monitoring.pihole ? "available" : "unavailable")
                        LabeledContent("Minecraft tick metrics", value: capabilities.monitoring.minecraftTickMetrics ? "available" : "unavailable")
                        if !capabilities.monitoring.minecraftControlActions.isEmpty {
                            LabeledContent("Minecraft controls", value: capabilities.monitoring.minecraftControlActions.joined(separator: ", "))
                        }
                        LabeledContent("Push notifications", value: capabilities.notifications.push ? "enabled" : "not configured")
                    }
                }

                Section("About") {
                    LabeledContent("Beacon", value: appVersion)
                    LabeledContent("Backend", value: model.backendVersion ?? "unknown")
                    LabeledContent("Rendering", value: "SwiftUI · native")
                    Text("Beacon is a native SwiftUI app. It contains no web views, no web bundle and no third-party dependencies.")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }

                Section {
                    Button("Disconnect from server", role: .destructive) {
                        showDisconnect = true
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .confirmationDialog(
                "Disconnect from this server?",
                isPresented: $showDisconnect,
                titleVisibility: .visible
            ) {
                Button("Disconnect", role: .destructive) {
                    model.signOut()
                    dismiss()
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("The token and pin are removed from the Keychain. You can reconnect with a new token at any time.")
            }
        }
    }

    private var appVersion: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(version) (\(build))"
    }

    private func testConnection() {
        testing = true
        Task {
            await model.refresh()
            testing = false
            if let error = model.errorMessage {
                testResult = error
                testSucceeded = false
            } else {
                testResult = "Reached the server and refreshed the dashboard."
                testSucceeded = true
            }
        }
    }
}
