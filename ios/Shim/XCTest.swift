// XCTest surface mock — ONLY for typechecking Beacon's test sources on Linux.
// The real tests run under Xcode (CI) or SwiftPM for the Foundation-only subset.

@_exported import Foundation

open class XCTestCase {
    public init() {}
    open func add(_ attachment: XCTAttachment) {}
}

public final class XCTAttachment {
    public enum Lifetime {
        case keepAlways
        case deleteOnSuccess
        case deleteOnFailure
    }

    public var name: String?
    public var lifetime: Lifetime = .deleteOnSuccess

    public init(contentsOfFile url: URL) {}
}

public func XCTFail(
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertTrue(
    _ expression: @autoclosure () -> Bool,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertFalse(
    _ expression: @autoclosure () -> Bool,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertEqual<T: Equatable>(
    _ expression1: @autoclosure () -> T,
    _ expression2: @autoclosure () -> T,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertNil<T>(
    _ expression: @autoclosure () -> T?,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertNotNil<T>(
    _ expression: @autoclosure () -> T?,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertGreaterThan<T: Comparable>(
    _ expression1: @autoclosure () -> T,
    _ expression2: @autoclosure () -> T,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertGreaterThanOrEqual<T: Comparable>(
    _ expression1: @autoclosure () -> T,
    _ expression2: @autoclosure () -> T,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}

public func XCTAssertLessThanOrEqual<T: Comparable>(
    _ expression1: @autoclosure () -> T,
    _ expression2: @autoclosure () -> T,
    _ message: @autoclosure () -> String = "",
    file: StaticString = #filePath,
    line: UInt = #line
) {}
