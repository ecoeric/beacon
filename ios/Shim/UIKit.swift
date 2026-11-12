// UIKit surface mock — ONLY for typechecking Beacon's SwiftUI code with a Linux Swift compiler.
// It is not UIKit, not an iOS SDK, and never ships in the app.

@_exported import Foundation

public enum UIUserInterfaceStyle {
    case unspecified
    case light
    case dark
}

public final class UITraitCollection {
    public var userInterfaceStyle: UIUserInterfaceStyle = .light
    public init() {}
}

open class UIColor {
    public init(red: CGFloat, green: CGFloat, blue: CGFloat, alpha: CGFloat) {}
    public init(white: CGFloat, alpha: CGFloat) {}
    public init(dynamicProvider: @escaping (UITraitCollection) -> UIColor) {}

    open func withAlphaComponent(_ alpha: CGFloat) -> UIColor { self }

    public static let white = UIColor(white: 1, alpha: 1)
    public static let black = UIColor(white: 0, alpha: 1)
    public static let clear = UIColor(white: 0, alpha: 0)
}

open class UIImage {
    public init?(data: Data) {}
    public init?(contentsOfFile path: String) {}
    open func pngData() -> Data? { nil }
}

public enum UIKeyboardType {
    case `default`
    case URL
    case emailAddress
    case numberPad
}
