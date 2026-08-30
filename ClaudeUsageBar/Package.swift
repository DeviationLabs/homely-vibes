// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ClaudeUsageBar",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "ClaudeUsageBar",
            path: "Sources/ClaudeUsageBar",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "ClaudeUsageBarTests",
            dependencies: ["ClaudeUsageBar"],
            path: "Tests/ClaudeUsageBarTests",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
