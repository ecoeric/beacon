import XCTest
@testable import BeaconValidationTests

fileprivate extension ModelDecodingTests {
    @available(*, deprecated, message: "Not actually deprecated. Marked as deprecated to allow inclusion of deprecated tests (which test deprecated functionality) without warnings")
    static nonisolated(unsafe) let __allTests__ModelDecodingTests = [
        ("testActivityAndMilestonesDecodeAsArrays", testActivityAndMilestonesDecodeAsArrays),
        ("testAgentStatusDecodesEnumsAndNestedSession", testAgentStatusDecodesEnumsAndNestedSession),
        ("testCapabilities", testCapabilities),
        ("testDashboardSummaryDecodesEverything", testDashboardSummaryDecodesEverything),
        ("testFormattingHelpers", testFormattingHelpers),
        ("testHealth", testHealth),
        ("testMinecraftLogs", testMinecraftLogs),
        ("testMinecraftStatusAndProtocolKeyMapping", testMinecraftStatusAndProtocolKeyMapping),
        ("testPiholeStatus", testPiholeStatus),
        ("testQueueMessageContract", testQueueMessageContract),
        ("testServerConfigurationParsing", testServerConfigurationParsing),
        ("testServerOverviewMetrics", testServerOverviewMetrics),
        ("testStatusSummaryIsDeterministicText", testStatusSummaryIsDeterministicText)
    ]
}
@available(*, deprecated, message: "Not actually deprecated. Marked as deprecated to allow inclusion of deprecated tests (which test deprecated functionality) without warnings")
func __BeaconValidationTests__allTests() -> [XCTestCaseEntry] {
    return [
        testCase(ModelDecodingTests.__allTests__ModelDecodingTests)
    ]
}