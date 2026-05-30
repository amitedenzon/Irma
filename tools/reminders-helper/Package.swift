// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "RemindersHelper",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "RemindersHelper",
            path: "Sources/RemindersHelper",
            exclude: ["Info.plist"],
            linkerSettings: [
                .linkedFramework("EventKit"),
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/RemindersHelper/Info.plist",
                ]),
            ]
        ),
    ]
)
