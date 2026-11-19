// Formatting.swift
// Beacon
//
// Presentation helpers shared by every screen. Foundation only (Linux-testable).

import Foundation

enum Format {
    static let byteFormatter: ByteCountFormatter = {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .memory
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB, .useTB]
        formatter.isAdaptive = true
        return formatter
    }()

    static func bytes(_ value: Int?) -> String {
        guard let value else { return "—" }
        return byteFormatter.string(fromByteCount: Int64(value))
    }

    static func bytes(_ value: Double?) -> String {
        guard let value else { return "—" }
        return byteFormatter.string(fromByteCount: Int64(value))
    }

    static func rate(_ bytesPerSecond: Double) -> String {
        let value = max(0, bytesPerSecond)
        if value < 1024 { return String(format: "%.0f B/s", value) }
        if value < 1024 * 1024 { return String(format: "%.0f KB/s", value / 1024) }
        return String(format: "%.1f MB/s", value / (1024 * 1024))
    }

    static func percent(_ value: Double?, digits: Int = 0) -> String {
        guard let value else { return "—" }
        return String(format: "%.\(digits)f%%", value)
    }

    static func celsius(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.0f°C", value)
    }

    static func watts(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.0f W", value)
    }

    static func count(_ value: Int?) -> String {
        guard let value else { return "—" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: value)) ?? "\(value)"
    }

    /// Relative age, e.g. "12s ago", "4m ago", "3h ago", "2d ago".
    static func age(_ timestamp: Double?, now: Date = Date()) -> String {
        guard let timestamp else { return "never" }
        let seconds = max(0, now.timeIntervalSince1970 - timestamp)
        if seconds < 5 { return "just now" }
        if seconds < 90 { return "\(Int(seconds))s ago" }
        if seconds < 5400 { return "\(Int(seconds / 60))m ago" }
        if seconds < 129_600 { return "\(Int(seconds / 3600))h ago" }
        return "\(Int(seconds / 86_400))d ago"
    }

    /// Duration such as "3d 4h", "5h 12m", "42m".
    static func duration(_ seconds: Double?) -> String {
        guard let seconds, seconds >= 0 else { return "—" }
        let total = Int(seconds)
        let days = total / 86_400
        let hours = (total % 86_400) / 3600
        let minutes = (total % 3600) / 60
        if days > 0 { return "\(days)d \(hours)h" }
        if hours > 0 { return "\(hours)h \(minutes)m" }
        return "\(minutes)m"
    }

    static func clock(_ timestamp: Double?) -> String {
        guard let timestamp else { return "—" }
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: timestamp))
    }

    /// Day separator used by the full chat transcript.
    static func chatDay(_ timestamp: Double, now: Date = Date()) -> String {
        let date = Date(timeIntervalSince1970: timestamp)
        let calendar = Calendar.current
        if calendar.isDateInToday(date) { return "Today" }
        if calendar.isDateInYesterday(date) { return "Yesterday" }
        let formatter = DateFormatter()
        formatter.dateFormat = calendar.isDate(date, equalTo: now, toGranularity: .year)
            ? "EEEE, d MMM"
            : "d MMM yyyy"
        return formatter.string(from: date)
    }

    static func dayAndTime(_ timestamp: Double?) -> String {
        guard let timestamp else { return "—" }
        let formatter = DateFormatter()
        formatter.dateFormat = "d MMM · HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: timestamp))
    }

    static func expiry(_ expiresAt: Double, now: Date = Date()) -> String {
        let remaining = expiresAt - now.timeIntervalSince1970
        if remaining <= 0 { return "expired" }
        if remaining < 86_400 { return "expires in \(Int(remaining / 3600))h" }
        return "expires in \(Int(remaining / 86_400))d"
    }
}
