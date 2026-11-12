// Platform stand-ins for the two iOS-only files excluded from the typecheck:
// Networking/Keychain.swift (Security) and Networking/PinnedSession.swift (Security/CryptoKit).
// AppSettings/AppModel only need these surfaces.

import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct KeychainStore {
    let service = "dev.ericserver.beacon"

    func set(_ value: String, account: String) throws {}
    func get(account: String) -> String? { nil }
    func delete(account: String) {}
}

enum PinnedSessionFactory {
    static func make(configuration: ServerConfiguration) -> URLSession {
        URLSession.shared
    }
}
