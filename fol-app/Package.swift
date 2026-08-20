// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "FOL",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "FOL", targets: ["FOL"]),
    ],
    dependencies: [
        .package(url: "https://github.com/MrKai77/DynamicNotchKit", branch: "main"),
    ],
    targets: [
        .executableTarget(
            name: "FOL",
            dependencies: ["DynamicNotchKit"],
            path: ".",
            exclude: ["Info.plist", "Package.swift", "FOL.entitlements"],
            resources: [
                .process("Assets.xcassets"),
                .copy("Resources")
            ],
            swiftSettings: [
                // Relax Swift 6 strict concurrency checking for this codebase.
                // The code predates strict Sendable/MainActor annotations and
                // adding them across ~30 files is backlogged.
                .unsafeFlags(["-Xfrontend", "-strict-concurrency=minimal"]),
            ]
        ),
    ]
)
