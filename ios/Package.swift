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
// The SwiftUI layer is validated separately: all Swift sources are at least parsed by
// `swiftc -parse` (scripts/validate_ios.sh) and compiled by Xcode on macOS.

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
