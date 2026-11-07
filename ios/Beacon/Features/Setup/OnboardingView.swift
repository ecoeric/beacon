// OnboardingView.swift
// Beacon
//
// First launch: server address, API token and the optional SPKI pin. Nothing is stored until
// the server has been reached and the token has been accepted.

import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var model: AppModel
    @State private var baseURL: String = AppSettings.shared.baseURLString
    @State private var token: String = ""
    @State private var pin: String = ""
    @State private var isConnecting = false
    @FocusState private var focusedField: Field?

    private enum Field {
        case address, token, pin
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                form
                if let error = model.setupError {
                    ErrorBanner(message: error)
                }
                connectButton
                instructions
            }
            .padding(Theme.screenPadding)
            .padding(.top, 24)
            .frame(maxWidth: 560, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .beaconScreen()
        .scrollDismissesKeyboard(.interactively)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Theme.accent.opacity(0.14))
                    .frame(width: 62, height: 62)
                Image(systemName: "dot.radiowaves.left.and.right")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(Theme.accent)
            }
            Text("Beacon")
                .font(.beaconDisplay)
            Text("Your server, in one quiet panel. Monitor the host, Pi-hole and Minecraft, follow the AI agent's progress, and send it work without interrupting it.")
                .font(.beaconBody)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var form: some View {
        VStack(spacing: 0) {
            fieldRow(label: "Server") {
                TextField("192.168.1.83:8091", text: $baseURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .focused($focusedField, equals: .address)
                    .multilineTextAlignment(.trailing)
            }
            DividerLine()
            fieldRow(label: "Token") {
                SecureField("paste ios.token", text: $token)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focusedField, equals: .token)
                    .multilineTextAlignment(.trailing)
            }
            DividerLine()
            fieldRow(label: "Pin") {
                TextField("optional SPKI pin", text: $pin)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.beaconMono)
                    .focused($focusedField, equals: .pin)
                    .multilineTextAlignment(.trailing)
            }
        }
        .beaconCard()
    }

    private func fieldRow<Content: View>(label: String, @ViewBuilder content: () -> Content) -> some View {
        HStack(spacing: 12) {
            Text(label)
                .font(.beaconBody)
                .foregroundStyle(.secondary)
                .frame(width: 70, alignment: .leading)
            content()
        }
        .padding(.vertical, 10)
    }

    private var connectButton: some View {
        Button {
            Task {
                isConnecting = true
                _ = await model.signIn(baseURLString: baseURL, token: token, pin: pin)
                isConnecting = false
            }
        } label: {
            HStack(spacing: 8) {
                if isConnecting { ProgressView().controlSize(.small).tint(.white) }
                Text(isConnecting ? "Connecting…" : "Connect")
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(BeaconPrimaryButtonStyle())
        .disabled(isConnecting)
    }

    private var instructions: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Where do these come from?")
                .font(.beaconCaption)
                .foregroundStyle(.secondary)
            Text("On the server:\n  beacon token create ios --scopes read,action,admin\n  beacon tls show")
                .font(.beaconMono)
                .foregroundStyle(.secondary)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
            Text("The token is kept in the iOS Keychain. Traffic is validated against the private Beacon CA bundled in the app; the pin adds a second, mandatory check when supplied.")
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

#Preview {
    OnboardingView()
        .environmentObject(AppModel())
}
