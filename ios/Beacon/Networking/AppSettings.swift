// AppSettings.swift
// Beacon
//
// Persistence for the server address (UserDefaults) and secrets (Keychain).

import Foundation

final class AppSettings {
    static let shared = AppSettings()

    private enum Keys {
        static let baseURL = "beacon.baseURLString"
        static let tokenAccount = "apiToken"
        static let pinAccount = "spkiPin"
    }

    private let defaults: UserDefaults
    private let keychain: KeychainStore

    init(defaults: UserDefaults = .standard, keychain: KeychainStore = KeychainStore()) {
        self.defaults = defaults
        self.keychain = keychain
    }

    var baseURLString: String {
        get { defaults.string(forKey: Keys.baseURL) ?? ServerConfiguration.defaultBaseURL.absoluteString }
        set { defaults.set(newValue, forKey: Keys.baseURL) }
    }

    var token: String? {
        get { keychain.get(account: Keys.tokenAccount) }
        set {
            if let newValue, !newValue.isEmpty {
                try? keychain.set(newValue, account: Keys.tokenAccount)
            } else {
                keychain.delete(account: Keys.tokenAccount)
            }
        }
    }

    var spkiPin: String? {
        get { keychain.get(account: Keys.pinAccount) }
        set {
            if let newValue, !newValue.isEmpty {
                try? keychain.set(newValue, account: Keys.pinAccount)
            } else {
                keychain.delete(account: Keys.pinAccount)
            }
        }
    }

    var isConfigured: Bool {
        configured() != nil
    }

    func configured() -> ServerConfiguration? {
        guard let token, !token.isEmpty,
              let url = ServerConfiguration.parse(baseURLString: baseURLString) else {
            return nil
        }
        return ServerConfiguration(baseURL: url, token: token, spkiPin: spkiPin)
    }

    func save(baseURLString: String, token: String, pin: String?) throws {
        guard let url = ServerConfiguration.parse(baseURLString: baseURLString) else {
            throw BeaconError.badURL
        }
        self.baseURLString = url.absoluteString
        self.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedPin = pin?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.spkiPin = (trimmedPin?.isEmpty ?? true) ? nil : trimmedPin
    }

    func clear() {
        token = nil
        spkiPin = nil
        defaults.removeObject(forKey: Keys.baseURL)
    }
}
