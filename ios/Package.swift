// swift-tools-version: 5.9
//
// Linux/macOS validation harness for the shared parts of the Beacon iOS app.
//
// Xcode and the iOS SDK are not available on the server, but the models, formatting helpers,
// the server configuration and the entire networking client are Foundation-only. This package
// compiles exactly those files and runs the same decoding tests as the Xcode unit-test target,
// so the JSON contract is verified with a real Swift compiler on every change.
//
//   cd ios && swift test
//
// The SwiftUI layer is validated separately: every app and test source is typechecked against
// mock SwiftUI/UIKit/Combine/XCTest modules by scripts/typecheck_ios_views.sh (real Swift
// compiler), all sources are parsed, and the real iOS-SDK build runs in CI (.github/workflows).

import PackageDescription

let package = Package(
    name: "BeaconValidation",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .library(name: "BeaconModels", targets: ["BeaconModels"])
    ],
    targets: [
        .target(
            name: "BeaconModels",
            path: "Beacon",
            sources: [
                "Models/Models.swift",
                "Models/Formatting.swift",
                "Networking/ServerConfiguration.swift",
                "Networking/APIClient.swift"
            ]
        ),
        .testTarget(
            name: "BeaconValidationTests",
            dependencies: ["BeaconModels"],
            path: "SharedTests"
        )
    ]
)
