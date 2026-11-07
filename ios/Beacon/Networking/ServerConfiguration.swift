// ServerConfiguration.swift
// Beacon
//
// Everything needed to talk to one Beacon deployment. Foundation only, so this file is
// compiled and exercised by the Linux validation harness as well as by the iOS app.

import Foundation

struct ServerConfiguration: Equatable {
    /// e.g. https://192.168.1.83:8091
    let baseURL: URL
    /// Bearer token created by `beacon token create` (never committed, stored in the Keychain).
    let token: String
    /// Optional base64url SHA-256 of the server certificate's SubjectPublicKeyInfo.
    /// When present it is enforced in addition to the bundled private-CA anchor.
    let spkiPin: String?

    var apiBase: URL {
        baseURL.appendingPathComponent("api/v1")
    }

    func endpoint(_ path: String, query: [URLQueryItem] = []) -> URL? {
        var components = URLComponents(
            url: apiBase.appendingPathComponent(path.hasPrefix("/") ? String(path.dropFirst()) : path),
            resolvingAgainstBaseURL: false
        )
        if !query.isEmpty {
            components?.queryItems = query
        }
        return components?.url
    }

    /// "192.168.1.83:8091" — used in the settings screen and status banners.
    var displayHost: String {
        let host = baseURL.host ?? baseURL.absoluteString
        if let port = baseURL.port {
            return "\(host):\(port)"
        }
        return host
    }

    static let defaultBaseURL = URL(string: "https://192.168.1.83:8091")!

    static func parse(baseURLString: String) -> URL? {
        let trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let candidate = trimmed.contains("://") ? trimmed : "https://\(trimmed)"
        guard let url = URL(string: candidate), url.host != nil else { return nil }
        return url
    }
}
