// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "SecondSelf",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "SecondSelf", targets: ["SecondSelf"]),
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "SecondSelf",
            dependencies: [],
            path: ".",
            exclude: ["Info.plist", "Package.swift", "SecondSelf.entitlements"],
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
