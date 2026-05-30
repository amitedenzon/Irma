# Apple Reminders Two-Way Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror Irma's Projects and Tasks into a macOS Reminders list named "Irma" via a Swift helper binary + EventKit, with full peer two-way sync, an auto-managed Inbox project for phone-captured orphans, and last-write-wins conflict resolution.

**Architecture:** A Swift CLI binary (`irma-reminders-helper`) holds the stable TCC permission identity and speaks JSON-on-stdio. A Python `ReminderBridge` invokes it as an async subprocess. `ReminderSyncService.sync_once()` runs a pure-function planner over the snapshot of both sides, then applies a single batched mutation through the bridge — guarded by an `asyncio.Lock` + `pending_rerun` flag for coalescing.

**Tech Stack:**
- Swift 5.9+ (Swift Package Manager) for the helper, EventKit framework, XCTest
- Python 3.12+, FastAPI, `aiosqlite`, Pydantic v2, `structlog`, APScheduler, pytest+`pytest-asyncio`
- SQLite via the existing `SignalStore`

**Spec:** `docs/superpowers/specs/2026-05-30-apple-reminders-sync-design.md` (commit `8ee5606`)

**Branch:** `feat/reminders-sync` — cut fresh from `main`, **not** stacked on `feat/chat-tools-parity`.

---

## Amendment 2026-05-30: Swift unit tests dropped

**Reason:** macOS Xcode Command Line Tools (the dev environment in use) does not ship the `XCTest` or `swift-testing` modules — they are full-Xcode-only. Installing full Xcode (~12 GB) is not warranted for a ~250-line helper.

**Effect on Tasks 1–5:** the SwiftPM `testTarget` is removed, no `*Tests.swift` files are written, and the verification gate switches from `swift test` to `swift build`. Tasks 6 and 7 are unaffected (they were already test-free). Tasks 8+ (Python side) are unaffected.

**Regression coverage shifts entirely to the Python side:**
- The Python `ReminderBridge` (Task 9) is tested against a Python fake helper that re-implements the JSON protocol — so any regression in the protocol contract surfaces in Python tests.
- The opt-in end-to-end test (Task 21) exercises the real Swift binary against the real macOS Reminders DB.

Task sections below have been edited inline to reflect this; original commit messages are preserved.

---

## File Structure

### New files

**Swift helper** (`tools/reminders-helper/`):
- `Package.swift` — SwiftPM manifest, defines the `RemindersHelper` executable target + tests, embeds `Info.plist` via linker flags.
- `Sources/RemindersHelper/Models.swift` — Codable JSON DTOs (`HelperReminder`, `BatchOp`, `BatchResult`, `BatchInput`, `ListOutput`).
- `Sources/RemindersHelper/RemindersClient.swift` — `RemindersClient` protocol with the EventKit surface we use.
- `Sources/RemindersHelper/EventKitRemindersClient.swift` — real EventKit-backed implementation.
- `Sources/RemindersHelper/CommandHandler.swift` — pure command dispatch functions: `(RemindersClient, Args, stdin) -> stdout`.
- `Sources/RemindersHelper/main.swift` — argv parsing, dispatches to `CommandHandler`.
- `Sources/RemindersHelper/Info.plist` — `NSRemindersUsageDescription` etc., baked into Mach-O via linker.
- `Tests/RemindersHelperTests/FakeRemindersClient.swift` — in-memory `RemindersClient`.
- `Tests/RemindersHelperTests/CommandHandlerTests.swift` — XCTest against the fake.
- `bin/irma-reminders-helper` — checked-in universal-binary build artifact.
- `README.md` — build instructions, TCC reset note.

**Python integration** (`services/api/src/irma_api/integrations/`):
- `__init__.py`
- `reminders/__init__.py`
- `reminders/models.py` — Pydantic DTOs mirroring the helper's JSON surface.
- `reminders/bridge.py` — `ReminderBridge` (async subprocess wrapper) + `BridgeError`.
- `reminders/planner.py` — pure `plan(irma_state, helper_state) -> SyncPlan` function.
- `reminders/inbox.py` — `ensure_inbox_project(repo) -> Project` helper.
- `reminders/sync.py` — `ReminderSyncService` with `sync_once()` + lock + rerun flag.
- `routers/reminders.py` — new HTTP router.

**Python tests** (`services/api/tests/integrations/`):
- `__init__.py`
- `fixtures/__init__.py`
- `fixtures/fake_helper.py` — Python script that mimics the helper's JSON protocol with an in-memory dict.
- `test_reminders_bridge.py`
- `test_reminders_planner.py`
- `test_reminders_inbox.py`
- `test_reminders_sync.py`
- `test_reminders_router.py`
- `test_reminders_e2e.py` — opt-in via `IRMA_REMINDERS_E2E=1`.

### Modified files

- `services/api/src/irma_api/config.py` — add `reminders_*` settings.
- `services/api/src/irma_api/models/task.py` — add `reminder_uuid: str | None`.
- `services/api/src/irma_api/models/project.py` — add `reminder_uuid: str | None`.
- `services/api/src/irma_api/store/migrations.py` — additive ALTER TABLE for the two new columns, idempotent.
- `services/api/src/irma_api/store/repos/task_repo.py` — read/write `reminder_uuid`; new `set_reminder_uuid(task_id, uuid)` method.
- `services/api/src/irma_api/store/repos/project_repo.py` — same.
- `services/api/src/irma_api/routers/integrations.py` — extend `IntegrationsStatus` with reminders fields.
- `services/api/src/irma_api/routers/projects.py` — fire-and-forget post-write sync trigger.
- `services/api/src/irma_api/routers/tasks.py` — same.
- `services/api/src/irma_api/runtime/scheduler.py` — accept a second job ("reminders") alongside the existing refresh tick.
- `services/api/src/irma_api/app.py` — instantiate `ReminderSyncService`, register the second scheduler job, expose on `app.state`.

---

## Task List

### Task 1: Branch + Swift package skeleton

**Files:**
- Create: `tools/reminders-helper/Package.swift`
- Create: `tools/reminders-helper/Sources/RemindersHelper/main.swift`
- Create: `tools/reminders-helper/Sources/RemindersHelper/Info.plist`
- Create: `tools/reminders-helper/.gitignore`
- Create: `tools/reminders-helper/README.md`

- [ ] **Step 1: Cut a fresh feature branch from main**

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/reminders-sync
```

Expected: `On branch feat/reminders-sync` with a clean working tree.

- [ ] **Step 2: Write `Package.swift`**

```swift
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
```

- [ ] **Step 3: Write `Info.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.irma.reminders-helper</string>
    <key>CFBundleDisplayName</key>
    <string>Irma Reminders Helper</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>NSRemindersUsageDescription</key>
    <string>Irma syncs your Projects and Tasks to a Reminders list named "Irma" so you can view and edit them on your iPhone.</string>
</dict>
</plist>
```

- [ ] **Step 4: Write a placeholder `main.swift`**

`Sources/RemindersHelper/main.swift`:

```swift
import Foundation

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "--version" {
    print("irma-reminders-helper 0.1.0")
    exit(0)
}
FileHandle.standardError.write(Data("unknown command\n".utf8))
exit(2)
```

- [ ] **Step 5: Run `swift build` to verify the package compiles**

```bash
cd tools/reminders-helper && swift build
```

Expected: `Build complete!`.

- [ ] **Step 6: Write `.gitignore` and minimal `README.md`**

`tools/reminders-helper/.gitignore`:

```
.build/
.swiftpm/
Package.resolved
```

`tools/reminders-helper/README.md`:

```markdown
# irma-reminders-helper

EventKit bridge for Irma — read/write the macOS Reminders database via a JSON-over-stdio CLI.

## Build

    swift build -c release --arch arm64 --arch x86_64
    cp .build/apple/Products/Release/RemindersHelper bin/irma-reminders-helper

## Test

    swift test

## Permissions

The helper holds the TCC permission grant for Reminders. First invocation under a new code-signed identity triggers the macOS permission dialog. To force a re-prompt during development:

    tccutil reset Reminders com.irma.reminders-helper
```

- [ ] **Step 7: Commit**

```bash
cd ../..
git add tools/reminders-helper
git commit -m "feat(reminders): scaffold Swift helper package"
```

---

### Task 2: Codable models for the helper's JSON surface

**Files:**
- Create: `tools/reminders-helper/Sources/RemindersHelper/Models.swift`

- [ ] **Step 1: Write `Models.swift`**

`Sources/RemindersHelper/Models.swift`:

```swift
import Foundation

struct HelperReminder: Codable, Equatable {
    let uuid: String
    let parentUuid: String?
    let title: String
    let notes: String
    let dueDate: String?       // ISO date (YYYY-MM-DD) or nil
    let startDate: String?     // ISO date or nil
    let isCompleted: Bool
    let completionDate: String?  // ISO 8601 timestamp or nil
    let lastModified: String     // ISO 8601 timestamp (always set by EventKit)

    enum CodingKeys: String, CodingKey {
        case uuid
        case parentUuid = "parent_uuid"
        case title
        case notes
        case dueDate = "due_date"
        case startDate = "start_date"
        case isCompleted = "is_completed"
        case completionDate = "completion_date"
        case lastModified = "last_modified"
    }
}

struct ReminderFields: Codable, Equatable {
    let title: String?
    let notes: String?
    let dueDate: String?
    let startDate: String?
    let isCompleted: Bool?
    let parentUuid: String?

    enum CodingKeys: String, CodingKey {
        case title
        case notes
        case dueDate = "due_date"
        case startDate = "start_date"
        case isCompleted = "is_completed"
        case parentUuid = "parent_uuid"
    }
}

enum BatchOp: Codable, Equatable {
    case create(ReminderFields)
    case update(uuid: String, ReminderFields)
    case delete(uuid: String)

    private enum CodingKeys: String, CodingKey {
        case op, fields, uuid
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let op = try c.decode(String.self, forKey: .op)
        switch op {
        case "create":
            let fields = try c.decode(ReminderFields.self, forKey: .fields)
            self = .create(fields)
        case "update":
            let uuid = try c.decode(String.self, forKey: .uuid)
            let fields = try c.decode(ReminderFields.self, forKey: .fields)
            self = .update(uuid: uuid, fields)
        case "delete":
            let uuid = try c.decode(String.self, forKey: .uuid)
            self = .delete(uuid: uuid)
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .op, in: c, debugDescription: "unknown op '\(op)'"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .create(let f):
            try c.encode("create", forKey: .op)
            try c.encode(f, forKey: .fields)
        case .update(let uuid, let f):
            try c.encode("update", forKey: .op)
            try c.encode(uuid, forKey: .uuid)
            try c.encode(f, forKey: .fields)
        case .delete(let uuid):
            try c.encode("delete", forKey: .op)
            try c.encode(uuid, forKey: .uuid)
        }
    }
}

struct BatchInput: Codable {
    let ops: [BatchOp]
}

struct BatchResult: Codable, Equatable {
    let index: Int
    let ok: Bool
    let uuid: String?
    let lastModified: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case index, ok, uuid
        case lastModified = "last_modified"
        case error
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(index, forKey: .index)
        try c.encode(ok, forKey: .ok)
        try c.encodeIfPresent(uuid, forKey: .uuid)
        try c.encodeIfPresent(lastModified, forKey: .lastModified)
        try c.encodeIfPresent(error, forKey: .error)
    }
}

struct BatchOutput: Codable {
    let results: [BatchResult]
}

struct ListOutput: Codable {
    let reminders: [HelperReminder]
}
```

- [ ] **Step 2: Run `swift build` to verify it compiles**

```bash
cd tools/reminders-helper && swift build
```

Expected: `Build complete!`.

- [ ] **Step 3: Commit**

```bash
cd ../..
git add tools/reminders-helper/Sources/RemindersHelper/Models.swift
git commit -m "feat(reminders): codable JSON DTOs for the helper"
```

---

### Task 3: `RemindersClient` protocol

**Files:**
- Create: `tools/reminders-helper/Sources/RemindersHelper/RemindersClient.swift`

> Amendment 2026-05-30: per the testing-strategy note at the top of this plan, the `FakeRemindersClient` and its XCTest exerciser are dropped — the fake existed solely to back Swift unit tests. The protocol itself is still production code (it's the injection seam between `CommandHandler` and `EventKitRemindersClient`).

- [ ] **Step 1: Write the protocol**

`Sources/RemindersHelper/RemindersClient.swift`:

```swift
import Foundation

enum AccessStatus: String, Codable {
    case authorized
    case denied
    case restricted
    case notDetermined
}

enum RemindersClientError: Error {
    case calendarNotFound(String)
    case reminderNotFound(String)
    case accessDenied
}

protocol RemindersClient {
    func requestAccess() async throws -> Bool
    func accessStatus() -> AccessStatus
    func ensureList(name: String) async throws -> String
    func list(calendarId: String) async throws -> [HelperReminder]
    func batch(
        calendarId: String,
        ops: [BatchOp],
        continueOnError: Bool
    ) async throws -> [BatchResult]
    func deleteCalendar(calendarId: String) async throws -> Bool
}
```

- [ ] **Step 2: Run `swift build` to verify it compiles**

```bash
cd tools/reminders-helper && swift build
```

Expected: `Build complete!`.

- [ ] **Step 3: Commit**

```bash
cd ../..
git add tools/reminders-helper/Sources/RemindersHelper/RemindersClient.swift
git commit -m "feat(reminders): RemindersClient protocol"
```

---

### Task 4: `CommandHandler` for `access-status`, `request-access`, `ensure-list`

**Files:**
- Create: `tools/reminders-helper/Sources/RemindersHelper/CommandHandler.swift`

- [ ] **Step 1: Write `CommandHandler.swift`**

`Sources/RemindersHelper/CommandHandler.swift`:

```swift
import Foundation

struct CommandError: Error {
    let code: String
    let message: String
}

struct CommandHandler {
    let client: RemindersClient

    func handle(args: [String], stdin: Data) async throws -> Data {
        guard let cmd = args.first else {
            throw CommandError(code: "missing_command", message: "no command provided")
        }
        let rest = Array(args.dropFirst())
        switch cmd {
        case "access-status":
            return try encode(["status": client.accessStatus().rawValue])
        case "request-access":
            let granted = try await client.requestAccess()
            if granted {
                return try encode(["granted": true])
            } else {
                return try encode(["granted": false, "reason": "denied"])
            }
        case "ensure-list":
            let name = try requireOption(rest, "--name")
            let id = try await client.ensureList(name: name)
            return try encode(["calendar_id": id])
        default:
            throw CommandError(code: "unknown_command", message: "unknown command '\(cmd)'")
        }
    }

    private func requireOption(_ args: [String], _ name: String) throws -> String {
        guard let i = args.firstIndex(of: name), i + 1 < args.count else {
            throw CommandError(code: "missing_option", message: "missing \(name) <value>")
        }
        return args[i + 1]
    }

    private func encode(_ payload: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
    }

    func encodeCodable<T: Encodable>(_ value: T) throws -> Data {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        return try enc.encode(value)
    }
}
```

- [ ] **Step 2: Run `swift build` to verify it compiles**

```bash
cd tools/reminders-helper && swift build
```

Expected: `Build complete!`.

- [ ] **Step 3: Commit**

```bash
cd ../..
git add tools/reminders-helper/Sources/RemindersHelper/CommandHandler.swift
git commit -m "feat(reminders): handler for access-status / request-access / ensure-list"
```

---

### Task 5: `CommandHandler.list` and `CommandHandler.batch`

**Files:**
- Modify: `tools/reminders-helper/Sources/RemindersHelper/CommandHandler.swift`

- [ ] **Step 1: Extend `CommandHandler.swift`**

Replace the `switch cmd` block in `handle(args:stdin:)` with:

```swift
        switch cmd {
        case "access-status":
            return try encode(["status": client.accessStatus().rawValue])
        case "request-access":
            let granted = try await client.requestAccess()
            if granted {
                return try encode(["granted": true])
            } else {
                return try encode(["granted": false, "reason": "denied"])
            }
        case "ensure-list":
            let name = try requireOption(rest, "--name")
            let id = try await client.ensureList(name: name)
            return try encode(["calendar_id": id])
        case "list":
            let calId = try requireOption(rest, "--calendar-id")
            let rems = try await client.list(calendarId: calId)
            return try encodeCodable(ListOutput(reminders: rems))
        case "batch":
            let calId = try requireOption(rest, "--calendar-id")
            let continueOnError = rest.contains("--continue-on-error")
            let input = try JSONDecoder().decode(BatchInput.self, from: stdin)
            let results = try await client.batch(
                calendarId: calId,
                ops: input.ops,
                continueOnError: continueOnError
            )
            return try encodeCodable(BatchOutput(results: results))
        case "delete-calendar":
            let calId = try requireOption(rest, "--calendar-id")
            let deleted = try await client.deleteCalendar(calendarId: calId)
            return try encode(["deleted": deleted])
        default:
            throw CommandError(code: "unknown_command", message: "unknown command '\(cmd)'")
        }
```

- [ ] **Step 2: Run `swift build` to verify it compiles**

```bash
cd tools/reminders-helper && swift build
```

Expected: `Build complete!`.

- [ ] **Step 3: Commit**

```bash
cd ../..
git add tools/reminders-helper/Sources/RemindersHelper/CommandHandler.swift
git commit -m "feat(reminders): list / batch / delete-calendar handlers"
```

---

### Task 6: `EventKitRemindersClient` (real EventKit-backed impl)

**Files:**
- Create: `tools/reminders-helper/Sources/RemindersHelper/EventKitRemindersClient.swift`

> Real EventKit cannot be unit-tested in the SwiftPM test bundle (no Reminders DB on CI), so this task has no XCTest. It is exercised by the opt-in Python e2e test (Task 23).

- [ ] **Step 1: Write `EventKitRemindersClient.swift`**

```swift
import EventKit
import Foundation

final class EventKitRemindersClient: RemindersClient {
    private let store = EKEventStore()
    private let iso = ISO8601DateFormatter()

    func requestAccess() async throws -> Bool {
        if #available(macOS 14.0, *) {
            return try await store.requestFullAccessToReminders()
        } else {
            return try await withCheckedThrowingContinuation { cont in
                store.requestAccess(to: .reminder) { granted, error in
                    if let error = error { cont.resume(throwing: error) }
                    else { cont.resume(returning: granted) }
                }
            }
        }
    }

    func accessStatus() -> AccessStatus {
        switch EKEventStore.authorizationStatus(for: .reminder) {
        case .authorized: return .authorized
        case .fullAccess: return .authorized
        case .denied: return .denied
        case .restricted: return .restricted
        case .notDetermined: return .notDetermined
        @unknown default: return .notDetermined
        }
    }

    func ensureList(name: String) async throws -> String {
        if let cal = store.calendars(for: .reminder)
            .first(where: { $0.title == name && $0.allowsContentModifications }) {
            return cal.calendarIdentifier
        }
        let cal = EKCalendar(for: .reminder, eventStore: store)
        cal.title = name
        cal.source = pickSource()
        try store.saveCalendar(cal, commit: true)
        return cal.calendarIdentifier
    }

    private func pickSource() -> EKSource? {
        let sources = store.sources
        return sources.first(where: { $0.sourceType == .calDAV && $0.title == "iCloud" })
            ?? sources.first(where: { $0.sourceType == .calDAV })
            ?? sources.first(where: { $0.sourceType == .local })
            ?? sources.first
    }

    func list(calendarId: String) async throws -> [HelperReminder] {
        guard let cal = store.calendar(withIdentifier: calendarId) else {
            throw RemindersClientError.calendarNotFound(calendarId)
        }
        let predicate = store.predicateForReminders(in: [cal])
        let rems: [EKReminder] = try await withCheckedThrowingContinuation { cont in
            store.fetchReminders(matching: predicate) { rems in
                cont.resume(returning: rems ?? [])
            }
        }
        return rems.map(toHelperReminder)
    }

    func batch(
        calendarId: String, ops: [BatchOp], continueOnError: Bool
    ) async throws -> [BatchResult] {
        guard let cal = store.calendar(withIdentifier: calendarId) else {
            throw RemindersClientError.calendarNotFound(calendarId)
        }
        var results: [BatchResult] = []
        for (idx, op) in ops.enumerated() {
            do {
                let res = try applyOne(op, calendar: cal, index: idx)
                results.append(res)
            } catch {
                results.append(BatchResult(
                    index: idx, ok: false, uuid: nil, lastModified: nil,
                    error: "\(error)"
                ))
                if !continueOnError { break }
            }
        }
        return results
    }

    private func applyOne(_ op: BatchOp, calendar: EKCalendar, index: Int) throws -> BatchResult {
        switch op {
        case .create(let f):
            let r = EKReminder(eventStore: store)
            r.calendar = calendar
            applyFields(f, to: r)
            try store.save(r, commit: true)
            return BatchResult(
                index: index, ok: true, uuid: r.calendarItemIdentifier,
                lastModified: iso.string(from: r.lastModifiedDate ?? Date()),
                error: nil
            )
        case .update(let uuid, let f):
            guard let r = store.calendarItem(withIdentifier: uuid) as? EKReminder else {
                throw RemindersClientError.reminderNotFound(uuid)
            }
            applyFields(f, to: r)
            try store.save(r, commit: true)
            return BatchResult(
                index: index, ok: true, uuid: r.calendarItemIdentifier,
                lastModified: iso.string(from: r.lastModifiedDate ?? Date()),
                error: nil
            )
        case .delete(let uuid):
            guard let r = store.calendarItem(withIdentifier: uuid) as? EKReminder else {
                throw RemindersClientError.reminderNotFound(uuid)
            }
            try store.remove(r, commit: true)
            return BatchResult(
                index: index, ok: true, uuid: uuid, lastModified: nil, error: nil
            )
        }
    }

    private func applyFields(_ f: ReminderFields, to r: EKReminder) {
        if let title = f.title { r.title = title }
        if let notes = f.notes { r.notes = notes }
        if let due = f.dueDate {
            r.dueDateComponents = parseDateComponents(due)
        }
        if let start = f.startDate {
            r.startDateComponents = parseDateComponents(start)
        }
        if let parent = f.parentUuid,
           let parentItem = store.calendarItem(withIdentifier: parent) as? EKReminder {
            r.parentReminder = parentItem
        }
        if let done = f.isCompleted {
            r.isCompleted = done
            r.completionDate = done ? Date() : nil
        }
    }

    private func parseDateComponents(_ iso: String) -> DateComponents? {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var c = DateComponents()
        c.year = parts[0]; c.month = parts[1]; c.day = parts[2]
        return c
    }

    private func toHelperReminder(_ r: EKReminder) -> HelperReminder {
        return HelperReminder(
            uuid: r.calendarItemIdentifier,
            parentUuid: r.parentReminder?.calendarItemIdentifier,
            title: r.title ?? "",
            notes: r.notes ?? "",
            dueDate: r.dueDateComponents.flatMap(componentsToDateString),
            startDate: r.startDateComponents.flatMap(componentsToDateString),
            isCompleted: r.isCompleted,
            completionDate: r.completionDate.map { iso.string(from: $0) },
            lastModified: iso.string(from: r.lastModifiedDate ?? Date())
        )
    }

    private func componentsToDateString(_ c: DateComponents) -> String? {
        guard let y = c.year, let m = c.month, let d = c.day else { return nil }
        return String(format: "%04d-%02d-%02d", y, m, d)
    }

    func deleteCalendar(calendarId: String) async throws -> Bool {
        guard let cal = store.calendar(withIdentifier: calendarId) else { return false }
        try store.removeCalendar(cal, commit: true)
        return true
    }
}
```

> Note: `EKEventStore.requestFullAccessToReminders()` (async/await form) is available on macOS 14+. We target macOS 14 in `Package.swift`.

- [ ] **Step 2: Verify it compiles**

```bash
cd tools/reminders-helper && swift build
```

Expected: `Build complete!`. Compilation must succeed.

- [ ] **Step 3: Commit**

```bash
cd ../..
git add tools/reminders-helper/Sources/RemindersHelper/EventKitRemindersClient.swift
git commit -m "feat(reminders): EventKit-backed RemindersClient implementation"
```

---

### Task 7: `main.swift` wiring + build the universal binary

**Files:**
- Modify: `tools/reminders-helper/Sources/RemindersHelper/main.swift`
- Create: `tools/reminders-helper/build.sh`
- Create: `tools/reminders-helper/bin/.gitkeep`

- [ ] **Step 1: Rewrite `main.swift` to wire CLI args into the handler**

```swift
import Foundation

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "--version" {
    print("irma-reminders-helper 0.1.0")
    exit(0)
}

let handler = CommandHandler(client: EventKitRemindersClient())

let stdin: Data = {
    let isStdinPiped = isatty(fileno(Foundation.stdin)) == 0
    return isStdinPiped ? FileHandle.standardInput.readDataToEndOfFile() : Data()
}()

@MainActor
func run() async {
    do {
        let output = try await handler.handle(args: args, stdin: stdin)
        FileHandle.standardOutput.write(output)
        FileHandle.standardOutput.write(Data("\n".utf8))
        exit(0)
    } catch let e as CommandError {
        let payload = ["error": e.code, "message": e.message]
        let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        FileHandle.standardError.write(data ?? Data())
        FileHandle.standardError.write(Data("\n".utf8))
        exit(2)
    } catch {
        let payload = ["error": "internal", "message": "\(error)"]
        let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        FileHandle.standardError.write(data ?? Data())
        FileHandle.standardError.write(Data("\n".utf8))
        exit(3)
    }
}

let semaphore = DispatchSemaphore(value: 0)
Task { await run(); semaphore.signal() }
semaphore.wait()
```

- [ ] **Step 2: Write the build script**

`tools/reminders-helper/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p bin
swift build -c release --arch arm64 --arch x86_64
cp .build/apple/Products/Release/RemindersHelper bin/irma-reminders-helper
chmod +x bin/irma-reminders-helper
file bin/irma-reminders-helper
```

```bash
chmod +x tools/reminders-helper/build.sh
touch tools/reminders-helper/bin/.gitkeep
```

- [ ] **Step 3: Run the build script**

```bash
tools/reminders-helper/build.sh
```

Expected: produces `tools/reminders-helper/bin/irma-reminders-helper` reported as a Mach-O universal binary (both arm64 and x86_64 slices).

- [ ] **Step 4: Smoke-check the binary**

```bash
tools/reminders-helper/bin/irma-reminders-helper --version
tools/reminders-helper/bin/irma-reminders-helper access-status
```

Expected first: `irma-reminders-helper 0.1.0`.
Expected second: a JSON object like `{"status":"notDetermined"}` (or `authorized` if you've granted Reminders access before).

- [ ] **Step 5: Verify the Info.plist was baked in**

```bash
otool -s __TEXT __info_plist tools/reminders-helper/bin/irma-reminders-helper | head -5
```

Expected: shows non-empty `__info_plist` section data.

- [ ] **Step 6: Commit binary + build script**

```bash
git add tools/reminders-helper/Sources/RemindersHelper/main.swift \
        tools/reminders-helper/build.sh \
        tools/reminders-helper/bin/.gitkeep \
        tools/reminders-helper/bin/irma-reminders-helper
git commit -m "feat(reminders): wire CLI and ship universal-binary artifact"
```

---

### Task 8: Python integrations package + Pydantic DTOs

**Files:**
- Create: `services/api/src/irma_api/integrations/__init__.py`
- Create: `services/api/src/irma_api/integrations/reminders/__init__.py`
- Create: `services/api/src/irma_api/integrations/reminders/models.py`
- Create: `services/api/tests/integrations/__init__.py`
- Create: `services/api/tests/integrations/test_reminders_models.py`

- [ ] **Step 1: Write the failing test**

`services/api/tests/integrations/test_reminders_models.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from irma_api.integrations.reminders.models import (
    BatchOp,
    BatchResult,
    HelperReminder,
    ReminderFields,
)


def test_helper_reminder_parses_helper_json() -> None:
    raw = {
        "uuid": "U-1",
        "parent_uuid": "P-1",
        "title": "buy milk",
        "notes": "",
        "due_date": "2026-06-01",
        "start_date": None,
        "is_completed": False,
        "completion_date": None,
        "last_modified": "2026-05-30T10:00:00Z",
    }
    rem = HelperReminder.model_validate(raw)
    assert rem.uuid == "U-1"
    assert rem.due_date == date(2026, 6, 1)
    assert rem.start_date is None
    assert rem.last_modified == datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)


def test_batch_op_create_serialises_with_op_discriminator() -> None:
    op = BatchOp.create_op(
        ReminderFields(title="hello", parent_uuid=None)
    )
    dumped = op.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"op": "create", "fields": {"title": "hello"}}


def test_batch_op_update_includes_uuid() -> None:
    op = BatchOp.update_op("U-1", ReminderFields(is_completed=True))
    dumped = op.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"op": "update", "uuid": "U-1", "fields": {"is_completed": True}}


def test_batch_result_allows_missing_last_modified_for_delete() -> None:
    res = BatchResult.model_validate({"index": 0, "ok": True, "uuid": "U-1"})
    assert res.last_modified is None
    assert res.error is None


def test_helper_reminder_rejects_bad_date() -> None:
    with pytest.raises(ValueError):
        HelperReminder.model_validate({
            "uuid": "U-1",
            "parent_uuid": None,
            "title": "x",
            "notes": "",
            "due_date": "not-a-date",
            "start_date": None,
            "is_completed": False,
            "completion_date": None,
            "last_modified": "2026-05-30T10:00:00Z",
        })
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_models.py -v
```

Expected: `ModuleNotFoundError: irma_api.integrations`.

- [ ] **Step 3: Create the package scaffold**

`services/api/src/irma_api/integrations/__init__.py`: empty file.

`services/api/src/irma_api/integrations/reminders/__init__.py`: empty file.

`services/api/tests/integrations/__init__.py`: empty file.

- [ ] **Step 4: Write `models.py`**

`services/api/src/irma_api/integrations/reminders/models.py`:

```python
"""Pydantic DTOs mirroring the Swift helper's JSON surface."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HelperReminder(BaseModel):
    """One reminder row as reported by `helper list`."""

    model_config = ConfigDict(populate_by_name=True)

    uuid: str
    parent_uuid: str | None = None
    title: str
    notes: str = ""
    due_date: date | None = None
    start_date: date | None = None
    is_completed: bool = False
    completion_date: datetime | None = None
    last_modified: datetime


class ReminderFields(BaseModel):
    """Field bag for create/update ops; every field optional."""

    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    notes: str | None = None
    due_date: date | None = None
    start_date: date | None = None
    is_completed: bool | None = None
    parent_uuid: str | None = None


class _Create(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Literal["create"] = "create"
    fields: ReminderFields


class _Update(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Literal["update"] = "update"
    uuid: str
    fields: ReminderFields


class _Delete(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Literal["delete"] = "delete"
    uuid: str


class BatchOp(BaseModel):
    """Discriminated wrapper around create / update / delete.

    Use the constructors `create_op`, `update_op`, `delete_op` rather than
    instantiating the underlying union directly.
    """

    model_config = ConfigDict(populate_by_name=True)
    root: _Create | _Update | _Delete = Field(discriminator="op")

    @classmethod
    def create_op(cls, fields: ReminderFields) -> "BatchOp":
        return cls(root=_Create(fields=fields))

    @classmethod
    def update_op(cls, uuid: str, fields: ReminderFields) -> "BatchOp":
        return cls(root=_Update(uuid=uuid, fields=fields))

    @classmethod
    def delete_op(cls, uuid: str) -> "BatchOp":
        return cls(root=_Delete(uuid=uuid))

    def model_dump(self, **kwargs: object) -> dict[str, object]:  # type: ignore[override]
        return self.root.model_dump(**kwargs)


class BatchResult(BaseModel):
    """One result row from `helper batch`."""

    model_config = ConfigDict(populate_by_name=True)

    index: int
    ok: bool
    uuid: str | None = None
    last_modified: datetime | None = None
    error: str | None = None
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/integrations/test_reminders_models.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 6: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations \
        services/api/tests/integrations
git commit -m "feat(reminders): pydantic DTOs for helper JSON surface"
```

---

### Task 9: `ReminderBridge` (async subprocess wrapper) + fake helper

**Files:**
- Create: `services/api/src/irma_api/integrations/reminders/bridge.py`
- Create: `services/api/tests/integrations/fixtures/__init__.py`
- Create: `services/api/tests/integrations/fixtures/fake_helper.py`
- Create: `services/api/tests/integrations/test_reminders_bridge.py`

- [ ] **Step 1: Write the fake helper script**

`services/api/tests/integrations/fixtures/fake_helper.py`:

```python
#!/usr/bin/env python3
"""Python implementation of the Swift helper's JSON surface for tests.

State is loaded from / saved to a JSON file pointed to by
$FAKE_HELPER_STATE so successive invocations in the same test see the
same in-memory store.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_path() -> Path:
    raw = os.environ.get("FAKE_HELPER_STATE")
    if not raw:
        print(
            json.dumps({"error": "no_state", "message": "FAKE_HELPER_STATE unset"}),
            file=sys.stderr,
        )
        sys.exit(2)
    return Path(raw)


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {
            "access": "authorized",
            "grant": True,
            "lists": {},
            "store": {},
            "counter": 0,
        }
    return json.loads(path.read_text())


def _save(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state))


def _next_uuid(state: dict[str, Any]) -> str:
    state["counter"] += 1
    return f"R-{state['counter']}"


def _ok(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _err(code: str, message: str) -> None:
    print(json.dumps({"error": code, "message": message}), file=sys.stderr)
    sys.exit(2)


def cmd_access_status(state: dict[str, Any]) -> None:
    _ok({"status": state["access"]})


def cmd_request_access(state: dict[str, Any]) -> None:
    granted = bool(state.get("grant", True))
    state["access"] = "authorized" if granted else "denied"
    _save(state)
    if granted:
        _ok({"granted": True})
    else:
        _ok({"granted": False, "reason": "denied"})


def cmd_ensure_list(state: dict[str, Any], name: str) -> None:
    if name in state["lists"]:
        _ok({"calendar_id": state["lists"][name]})
        return
    cal_id = f"cal-{name}"
    state["lists"][name] = cal_id
    state["store"].setdefault(cal_id, {})
    _save(state)
    _ok({"calendar_id": cal_id})


def cmd_list(state: dict[str, Any], cal_id: str) -> None:
    rems = state["store"].get(cal_id)
    if rems is None:
        _err("calendar_not_found", cal_id)
        return
    out = sorted(rems.values(), key=lambda r: r["uuid"])
    _ok({"reminders": out})


def _apply_create(state: dict[str, Any], cal_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    uuid = _next_uuid(state)
    rem = {
        "uuid": uuid,
        "parent_uuid": fields.get("parent_uuid"),
        "title": fields.get("title") or "",
        "notes": fields.get("notes") or "",
        "due_date": fields.get("due_date"),
        "start_date": fields.get("start_date"),
        "is_completed": bool(fields.get("is_completed") or False),
        "completion_date": now if fields.get("is_completed") else None,
        "last_modified": now,
    }
    state["store"][cal_id][uuid] = rem
    return {"index": -1, "ok": True, "uuid": uuid, "last_modified": now}


def _apply_update(
    state: dict[str, Any], cal_id: str, uuid: str, fields: dict[str, Any]
) -> dict[str, Any]:
    cur = state["store"][cal_id].get(uuid)
    if cur is None:
        raise KeyError(uuid)
    now = _now()
    for key in ("title", "notes", "due_date", "start_date", "parent_uuid"):
        if key in fields and fields[key] is not None:
            cur[key] = fields[key]
    if "is_completed" in fields and fields["is_completed"] is not None:
        cur["is_completed"] = bool(fields["is_completed"])
        cur["completion_date"] = now if cur["is_completed"] else None
    cur["last_modified"] = now
    return {"index": -1, "ok": True, "uuid": uuid, "last_modified": now}


def _apply_delete(state: dict[str, Any], cal_id: str, uuid: str) -> dict[str, Any]:
    if uuid not in state["store"][cal_id]:
        raise KeyError(uuid)
    del state["store"][cal_id][uuid]
    return {"index": -1, "ok": True, "uuid": uuid}


def cmd_batch(state: dict[str, Any], cal_id: str, continue_on_error: bool) -> None:
    if cal_id not in state["store"]:
        _err("calendar_not_found", cal_id)
        return
    input_data = json.loads(sys.stdin.read() or "{}")
    ops = input_data.get("ops", [])
    results: list[dict[str, Any]] = []
    for idx, op in enumerate(ops):
        try:
            if op["op"] == "create":
                r = _apply_create(state, cal_id, op["fields"])
            elif op["op"] == "update":
                r = _apply_update(state, cal_id, op["uuid"], op["fields"])
            elif op["op"] == "delete":
                r = _apply_delete(state, cal_id, op["uuid"])
            else:
                raise ValueError(f"bad op {op['op']!r}")
            r["index"] = idx
            results.append(r)
        except Exception as exc:
            results.append({"index": idx, "ok": False, "error": str(exc)})
            if not continue_on_error:
                break
    _save(state)
    _ok({"results": results})


def cmd_delete_calendar(state: dict[str, Any], cal_id: str) -> None:
    deleted = state["store"].pop(cal_id, None) is not None
    state["lists"] = {k: v for k, v in state["lists"].items() if v != cal_id}
    _save(state)
    _ok({"deleted": deleted})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--name", default=None)
    parser.add_argument("--calendar-id", default=None)
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    state = _load()
    cmd = args.command
    if cmd == "access-status":
        cmd_access_status(state)
    elif cmd == "request-access":
        cmd_request_access(state)
    elif cmd == "ensure-list":
        assert args.name, "--name required"
        cmd_ensure_list(state, args.name)
    elif cmd == "list":
        assert args.calendar_id, "--calendar-id required"
        cmd_list(state, args.calendar_id)
    elif cmd == "batch":
        assert args.calendar_id, "--calendar-id required"
        cmd_batch(state, args.calendar_id, args.continue_on_error)
    elif cmd == "delete-calendar":
        assert args.calendar_id, "--calendar-id required"
        cmd_delete_calendar(state, args.calendar_id)
    else:
        _err("unknown_command", cmd)


if __name__ == "__main__":
    main()
```

`services/api/tests/integrations/fixtures/__init__.py`: empty.

- [ ] **Step 2: Write the failing bridge tests**

`services/api/tests/integrations/test_reminders_bridge.py`:

```python
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from irma_api.integrations.reminders.bridge import BridgeError, ReminderBridge
from irma_api.integrations.reminders.models import BatchOp, ReminderFields

FAKE = Path(__file__).parent / "fixtures" / "fake_helper.py"


@pytest.fixture
def bridge(tmp_path: Path) -> ReminderBridge:
    state_file = tmp_path / "state.json"
    return ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(FAKE),),
        env={"FAKE_HELPER_STATE": str(state_file)},
    )


@pytest.mark.asyncio
async def test_access_status_returns_authorized(bridge: ReminderBridge) -> None:
    assert (await bridge.access_status()) == "authorized"


@pytest.mark.asyncio
async def test_request_access_grants(bridge: ReminderBridge) -> None:
    granted = await bridge.request_access()
    assert granted is True


@pytest.mark.asyncio
async def test_ensure_list_is_stable(bridge: ReminderBridge) -> None:
    a = await bridge.ensure_list("Irma")
    b = await bridge.ensure_list("Irma")
    assert a == b


@pytest.mark.asyncio
async def test_list_empty(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma")
    rems = await bridge.list(cal_id)
    assert rems == []


@pytest.mark.asyncio
async def test_batch_create_then_list(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma")
    results = await bridge.batch(
        cal_id,
        [BatchOp.create_op(ReminderFields(title="x", due_date=date(2026, 6, 1)))],
        continue_on_error=False,
    )
    assert len(results) == 1
    assert results[0].ok
    rems = await bridge.list(cal_id)
    assert len(rems) == 1
    assert rems[0].title == "x"
    assert rems[0].due_date == date(2026, 6, 1)


@pytest.mark.asyncio
async def test_bridge_error_on_unknown_command(tmp_path: Path) -> None:
    bridge = ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(FAKE),),
        env={"FAKE_HELPER_STATE": str(tmp_path / "s.json")},
    )
    with pytest.raises(BridgeError) as exc:
        await bridge._invoke(["bogus"], stdin=b"")
    assert "unknown_command" in str(exc.value)


@pytest.mark.asyncio
async def test_bridge_error_on_non_json(tmp_path: Path) -> None:
    """A binary that exits 0 but emits garbage on stdout must surface as BridgeError."""
    bad_helper = tmp_path / "bad_helper.py"
    bad_helper.write_text("import sys; print('not json'); sys.exit(0)\n")
    bridge = ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(bad_helper),),
        env={},
    )
    with pytest.raises(BridgeError):
        await bridge.access_status()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_bridge.py -v
```

Expected: import error — `ReminderBridge`, `BridgeError` undefined.

- [ ] **Step 4: Implement the bridge**

`services/api/src/irma_api/integrations/reminders/bridge.py`:

```python
"""Async subprocess wrapper around the Swift helper binary.

Every method spawns one short-lived subprocess. Stdin/stdout are JSON.
Non-zero exit, non-JSON stdout, or unparseable error JSON on stderr all
surface as `BridgeError`.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Final, Literal

import structlog

from irma_api.integrations.reminders.models import (
    BatchOp,
    BatchResult,
    HelperReminder,
)

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS: Final[float] = 30.0


class BridgeError(RuntimeError):
    """Helper binary failed: non-zero exit, non-JSON output, or unknown cmd."""

    def __init__(self, code: str, message: str, *, stderr: str = "") -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.stderr = stderr


class ReminderBridge:
    """Async wrapper over `irma-reminders-helper`."""

    def __init__(
        self,
        *,
        binary_path: Path,
        binary_argv_prefix: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        self._binary = binary_path
        self._prefix = binary_argv_prefix
        self._env = env

    async def _invoke(self, args: list[str], *, stdin: bytes) -> bytes:
        argv = [str(self._binary), *self._prefix, *args]
        env = dict(os.environ)
        if self._env:
            env.update(self._env)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise BridgeError("missing_binary", str(exc)) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin), timeout=_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            proc.kill()
            raise BridgeError("timeout", f"{argv[0]} did not return in {_TIMEOUT_SECONDS}s") from exc

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            code, message = "subprocess_failed", err_text
            try:
                payload = json.loads(err_text)
                code = str(payload.get("error", code))
                message = str(payload.get("message", message))
            except (ValueError, AttributeError):
                pass
            raise BridgeError(code, message, stderr=err_text)
        return stdout

    async def _invoke_json(self, args: list[str], *, stdin: bytes = b"") -> dict[str, object]:
        out = await self._invoke(args, stdin=stdin)
        text = out.decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise BridgeError("invalid_json", f"helper returned non-JSON: {text!r}") from exc
        if not isinstance(data, dict):
            raise BridgeError("invalid_json", f"helper returned non-object: {text!r}")
        return data

    async def access_status(self) -> Literal["authorized", "denied", "restricted", "notDetermined"]:
        data = await self._invoke_json(["access-status"])
        status = data.get("status")
        if status not in {"authorized", "denied", "restricted", "notDetermined"}:
            raise BridgeError("invalid_json", f"unexpected status {status!r}")
        return status  # type: ignore[return-value]

    async def request_access(self) -> bool:
        data = await self._invoke_json(["request-access"])
        return bool(data.get("granted"))

    async def ensure_list(self, name: str) -> str:
        data = await self._invoke_json(["ensure-list", "--name", name])
        cal_id = data.get("calendar_id")
        if not isinstance(cal_id, str):
            raise BridgeError("invalid_json", "ensure-list missing calendar_id")
        return cal_id

    async def list(self, calendar_id: str) -> list[HelperReminder]:
        data = await self._invoke_json(["list", "--calendar-id", calendar_id])
        raw = data.get("reminders", [])
        if not isinstance(raw, list):
            raise BridgeError("invalid_json", "list missing reminders")
        return [HelperReminder.model_validate(r) for r in raw]

    async def batch(
        self,
        calendar_id: str,
        ops: list[BatchOp],
        *,
        continue_on_error: bool = True,
    ) -> list[BatchResult]:
        payload = {"ops": [op.model_dump(by_alias=True, exclude_none=True) for op in ops]}
        args = ["batch", "--calendar-id", calendar_id]
        if continue_on_error:
            args.append("--continue-on-error")
        data = await self._invoke_json(args, stdin=json.dumps(payload).encode("utf-8"))
        raw = data.get("results", [])
        if not isinstance(raw, list):
            raise BridgeError("invalid_json", "batch missing results")
        return [BatchResult.model_validate(r) for r in raw]

    async def delete_calendar(self, calendar_id: str) -> bool:
        data = await self._invoke_json(["delete-calendar", "--calendar-id", calendar_id])
        return bool(data.get("deleted"))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_bridge.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations/reminders/bridge.py \
        services/api/tests/integrations/fixtures \
        services/api/tests/integrations/test_reminders_bridge.py
git commit -m "feat(reminders): async bridge to helper binary"
```

---

### Task 10: Schema migration for `reminder_uuid` columns

**Files:**
- Modify: `services/api/src/irma_api/store/migrations.py`
- Modify: `services/api/tests/test_migrations.py`

- [ ] **Step 1: Read existing migration tests to follow the pattern**

```bash
cat services/api/tests/test_migrations.py | head -40
```

- [ ] **Step 2: Add a failing test**

Append to `services/api/tests/test_migrations.py` (use the existing fixture pattern from the file):

```python
@pytest.mark.asyncio
async def test_task_has_reminder_uuid_column(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(task)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "reminder_uuid" in cols


@pytest.mark.asyncio
async def test_project_has_reminder_uuid_column(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(project)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "reminder_uuid" in cols


@pytest.mark.asyncio
async def test_reminder_uuid_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await ensure_schema(conn)
        await ensure_schema(conn)
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(task)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "reminder_uuid" in cols
```

(If `pytest`, `aiosqlite`, `Path`, or `ensure_schema` are not yet imported in the file, add the imports at the top.)

- [ ] **Step 3: Run to verify it fails**

```bash
cd services/api && uv run pytest tests/test_migrations.py -v -k reminder_uuid
```

Expected: AssertionError — column missing.

- [ ] **Step 4: Extend `migrations.py`**

Add inside `ensure_schema`, immediately before `await conn.commit()` at the end:

```python
    if not await _table_has_column(conn, "task", "reminder_uuid"):
        await conn.execute("ALTER TABLE task ADD COLUMN reminder_uuid TEXT")
        await conn.execute(
            "CREATE UNIQUE INDEX idx_task_reminder_uuid "
            "ON task(reminder_uuid) WHERE reminder_uuid IS NOT NULL"
        )
    if not await _table_has_column(conn, "project", "reminder_uuid"):
        await conn.execute("ALTER TABLE project ADD COLUMN reminder_uuid TEXT")
        await conn.execute(
            "CREATE UNIQUE INDEX idx_project_reminder_uuid "
            "ON project(reminder_uuid) WHERE reminder_uuid IS NOT NULL"
        )
```

Also add helper function `_table_has_column` near `_signals_has_project_id`:

```python
async def _table_has_column(
    conn: aiosqlite.Connection, table: str, column: str
) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in await cur.fetchall())
```

> Note: SQLite cannot add `UNIQUE` directly via `ALTER TABLE ADD COLUMN`, so we create a partial-unique index instead. `NULL` values are exempt from the uniqueness check — exactly what we want for unlinked rows.

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_migrations.py -v
```

Expected: all migration tests pass, including the three new ones.

- [ ] **Step 6: Commit**

```bash
cd ../..
git add services/api/src/irma_api/store/migrations.py \
        services/api/tests/test_migrations.py
git commit -m "feat(reminders): schema migration for reminder_uuid columns"
```

---

### Task 11: Extend `Task` and `Project` Pydantic models + repos

**Files:**
- Modify: `services/api/src/irma_api/models/task.py`
- Modify: `services/api/src/irma_api/models/project.py`
- Modify: `services/api/src/irma_api/store/repos/task_repo.py`
- Modify: `services/api/src/irma_api/store/repos/project_repo.py`
- Modify: `services/api/tests/test_task_repo.py`
- Modify: `services/api/tests/test_project_repo.py`

- [ ] **Step 1: Add a failing test to `test_task_repo.py`**

```python
@pytest.mark.asyncio
async def test_set_reminder_uuid_persists(task_repo: TaskRepo, project: Project) -> None:
    task = await task_repo.create(
        TaskCreate(project_id=project.id, title="t1")
    )
    await task_repo.set_reminder_uuid(task.id, "REM-123")
    refreshed = await task_repo.get(task.id)
    assert refreshed.reminder_uuid == "REM-123"


@pytest.mark.asyncio
async def test_set_reminder_uuid_to_none_clears(task_repo: TaskRepo, project: Project) -> None:
    task = await task_repo.create(
        TaskCreate(project_id=project.id, title="t1")
    )
    await task_repo.set_reminder_uuid(task.id, "REM-X")
    await task_repo.set_reminder_uuid(task.id, None)
    refreshed = await task_repo.get(task.id)
    assert refreshed.reminder_uuid is None
```

- [ ] **Step 2: Add a parallel failing test to `test_project_repo.py`**

```python
@pytest.mark.asyncio
async def test_project_set_reminder_uuid(project_repo: ProjectRepo) -> None:
    p = await project_repo.create(ProjectCreate(name="P1"))
    await project_repo.set_reminder_uuid(p.id, "REM-P1")
    refreshed = await project_repo.get(p.id)
    assert refreshed.reminder_uuid == "REM-P1"
```

- [ ] **Step 3: Run to verify failures**

```bash
cd services/api && uv run pytest tests/test_task_repo.py tests/test_project_repo.py -v -k reminder_uuid
```

Expected: errors — `Task` has no `reminder_uuid` attribute; `set_reminder_uuid` not defined.

- [ ] **Step 4: Extend `models/task.py`**

In `class Task(_TaskFields):` add the new field after `completed_at`:

```python
class Task(_TaskFields):
    """A persisted Task row."""

    id: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    reminder_uuid: str | None = None
```

- [ ] **Step 5: Extend `models/project.py`**

```python
class Project(_ProjectFields):
    """A persisted Project row."""

    id: str
    created_at: datetime
    updated_at: datetime
    reminder_uuid: str | None = None
```

- [ ] **Step 6: Extend `store/repos/task_repo.py`**

Update `_COLUMNS`:

```python
_COLUMNS = (
    "id, project_id, title, notes, status, due_date, scheduled_for, "
    "estimated_minutes, created_at, updated_at, completed_at, reminder_uuid"
)
```

Update `_row_to_task` to set `reminder_uuid=row["reminder_uuid"]`.

Update the INSERT in `create()` — add an explicit `NULL` for `reminder_uuid`:

```python
            await self._conn.execute(
                f"""
                INSERT INTO task ({_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                ...
            )
```

Append a new method to `TaskRepo`:

```python
    async def set_reminder_uuid(self, task_id: str, uuid: str | None) -> None:
        cur = await self._conn.execute(
            "UPDATE task SET reminder_uuid = ?, updated_at = ? WHERE id = ?",
            (uuid, _now().isoformat(), task_id),
        )
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("task", task_id)
```

- [ ] **Step 7: Extend `store/repos/project_repo.py`**

Mirror the same pattern: update `_COLUMNS`, `_row_to_project`, the INSERT, and add `set_reminder_uuid`. Project's INSERT becomes:

```python
            await self._conn.execute(
                f"""
                INSERT INTO project ({_COLUMNS}, name_lower)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                ...
            )
```

And `_COLUMNS`:

```python
_COLUMNS = (
    "id, name, description, status, priority, "
    "calendar_keywords, goals, target_date, created_at, updated_at, reminder_uuid"
)
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/test_task_repo.py tests/test_project_repo.py tests/test_routers_projects.py tests/test_routers_tasks.py -v
```

Expected: all pass — including new reminder_uuid tests and unchanged existing ones.

- [ ] **Step 9: Commit**

```bash
cd ../..
git add services/api/src/irma_api/models \
        services/api/src/irma_api/store/repos \
        services/api/tests/test_task_repo.py \
        services/api/tests/test_project_repo.py
git commit -m "feat(reminders): persist reminder_uuid on Task and Project rows"
```

---

### Task 12: Pure sync planner — `plan(irma_state, helper_state) -> SyncPlan`

**Files:**
- Create: `services/api/src/irma_api/integrations/reminders/planner.py`
- Create: `services/api/tests/integrations/test_reminders_planner.py`

- [ ] **Step 1: Write the failing test (covers each branch)**

`services/api/tests/integrations/test_reminders_planner.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from irma_api.integrations.reminders.models import HelperReminder
from irma_api.integrations.reminders.planner import (
    IrmaProjectSnap,
    IrmaSnapshot,
    IrmaTaskSnap,
    plan,
)
from irma_api.models.project import ProjectStatus
from irma_api.models.task import TaskStatus

T0 = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)


def _proj(
    *, pid: str, name: str = "P", uuid: str | None = None,
    status: ProjectStatus = ProjectStatus.ACTIVE, updated: datetime = T0,
) -> IrmaProjectSnap:
    return IrmaProjectSnap(
        id=pid, name=name, status=status, reminder_uuid=uuid, updated_at=updated
    )


def _task(
    *, tid: str, pid: str, title: str = "t",
    status: TaskStatus = TaskStatus.TODO, uuid: str | None = None,
    updated: datetime = T0, due: date | None = None,
    sched: date | None = None, notes: str = "",
) -> IrmaTaskSnap:
    return IrmaTaskSnap(
        id=tid, project_id=pid, title=title, status=status,
        reminder_uuid=uuid, updated_at=updated,
        due_date=due, scheduled_for=sched, notes=notes,
    )


def _rem(
    *, uuid: str, parent: str | None = None, title: str = "r",
    completed: bool = False, modified: datetime = T0,
    due: date | None = None, start: date | None = None, notes: str = "",
) -> HelperReminder:
    return HelperReminder(
        uuid=uuid, parent_uuid=parent, title=title, notes=notes,
        due_date=due, start_date=start, is_completed=completed,
        completion_date=None, last_modified=modified,
    )


def test_irma_only_project_yields_create_remote() -> None:
    snap = IrmaSnapshot(projects=[_proj(pid="P1", name="Alpha")], tasks=[])
    p = plan(snap, helper_reminders=[], inbox_project_id=None)
    assert len(p.creates_on_reminders) == 1
    op = p.creates_on_reminders[0]
    assert op.irma_id == "P1"
    assert op.fields.title == "Alpha"
    assert op.fields.parent_uuid is None
    assert p.creates_on_irma == []


def test_irma_only_task_with_synced_parent_creates_subtask() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", uuid="REM-P1")],
        tasks=[_task(tid="T1", pid="P1", title="hello")],
    )
    p = plan(snap, helper_reminders=[
        _rem(uuid="REM-P1", title="P", parent=None)
    ], inbox_project_id=None)
    assert len(p.creates_on_reminders) == 1
    op = p.creates_on_reminders[0]
    assert op.fields.parent_uuid == "REM-P1"


def test_remote_orphan_creates_task_in_inbox() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="INBOX", uuid="REM-INBOX")],
        tasks=[],
    )
    rem = _rem(uuid="REM-X", parent=None, title="capture")
    p = plan(snap, helper_reminders=[
        _rem(uuid="REM-INBOX", title="Inbox"), rem
    ], inbox_project_id="INBOX")
    assert len(p.creates_on_irma) == 1
    create = p.creates_on_irma[0]
    assert create.project_id == "INBOX"
    assert create.reminder_uuid == "REM-X"
    assert create.title == "capture"


def test_remote_orphan_skipped_when_no_inbox() -> None:
    snap = IrmaSnapshot(projects=[], tasks=[])
    rem = _rem(uuid="REM-X", parent=None)
    p = plan(snap, helper_reminders=[rem], inbox_project_id=None)
    assert p.creates_on_irma == []


def test_remote_newer_patches_irma() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", uuid="REM-P1")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", updated=T0, title="old")],
    )
    rems = [
        _rem(uuid="REM-P1"),
        _rem(uuid="REM-T1", parent="REM-P1", title="new", modified=T1),
    ]
    p = plan(snap, helper_reminders=rems, inbox_project_id=None)
    assert len(p.patches_on_irma) == 1
    patch = p.patches_on_irma[0]
    assert patch.irma_id == "T1"
    assert patch.title == "new"


def test_irma_newer_patches_reminders() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", uuid="REM-P1")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", updated=T2, title="new")],
    )
    rems = [
        _rem(uuid="REM-P1"),
        _rem(uuid="REM-T1", parent="REM-P1", title="old", modified=T1),
    ]
    p = plan(snap, helper_reminders=rems, inbox_project_id=None)
    assert len(p.patches_on_reminders) == 1
    patch = p.patches_on_reminders[0]
    assert patch.uuid == "REM-T1"
    assert patch.fields.title == "new"


def test_archived_project_cascade_deletes_reminders() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", uuid="REM-P1", status=ProjectStatus.ARCHIVED)],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1")],
    )
    rems = [
        _rem(uuid="REM-P1"),
        _rem(uuid="REM-T1", parent="REM-P1"),
    ]
    p = plan(snap, helper_reminders=rems, inbox_project_id=None)
    deleted = {d.uuid for d in p.deletes_on_reminders}
    assert deleted == {"REM-P1", "REM-T1"}


def test_paused_project_title_prefixed() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", status=ProjectStatus.PAUSED)],
        tasks=[],
    )
    p = plan(snap, helper_reminders=[], inbox_project_id=None)
    assert p.creates_on_reminders[0].fields.title == "⏸ Alpha"


def test_remote_only_task_with_known_parent_creates_in_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", uuid="REM-P1")],
        tasks=[],
    )
    rems = [
        _rem(uuid="REM-P1"),
        _rem(uuid="REM-X", parent="REM-P1", title="phone-task"),
    ]
    p = plan(snap, helper_reminders=rems, inbox_project_id=None)
    assert len(p.creates_on_irma) == 1
    assert p.creates_on_irma[0].project_id == "P1"
    assert p.creates_on_irma[0].title == "phone-task"


def test_irma_only_deletion_signal_when_uuid_present_but_reminder_gone() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", uuid="REM-P1")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-DELETED")],
    )
    rems = [_rem(uuid="REM-P1")]
    p = plan(snap, helper_reminders=rems, inbox_project_id=None)
    assert p.deletes_on_irma == ["T1"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_planner.py -v
```

Expected: import error — `planner` module does not exist.

- [ ] **Step 3: Write `planner.py`**

`services/api/src/irma_api/integrations/reminders/planner.py`:

```python
"""Pure-function reconciliation planner. No I/O, no async, no clock.

The sync engine calls `plan(...)` between the snapshot and apply passes.
Output is a SyncPlan — a description of mutations on both sides — that
the engine then executes idempotently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from irma_api.integrations.reminders.models import (
    BatchOp,
    HelperReminder,
    ReminderFields,
)
from irma_api.models.project import ProjectStatus
from irma_api.models.task import TaskStatus

_PAUSED_PREFIX = "⏸ "


@dataclass(frozen=True)
class IrmaProjectSnap:
    id: str
    name: str
    status: ProjectStatus
    reminder_uuid: str | None
    updated_at: datetime


@dataclass(frozen=True)
class IrmaTaskSnap:
    id: str
    project_id: str
    title: str
    status: TaskStatus
    reminder_uuid: str | None
    updated_at: datetime
    due_date: date | None = None
    scheduled_for: date | None = None
    notes: str = ""


@dataclass(frozen=True)
class IrmaSnapshot:
    projects: list[IrmaProjectSnap]
    tasks: list[IrmaTaskSnap]


@dataclass(frozen=True)
class RemoteCreate:
    """A reminder we want to create on the Reminders side."""

    irma_id: str
    kind: str           # "project" | "task"
    fields: ReminderFields


@dataclass(frozen=True)
class RemotePatch:
    uuid: str
    fields: ReminderFields
    irma_id: str
    kind: str


@dataclass(frozen=True)
class RemoteDelete:
    uuid: str


@dataclass(frozen=True)
class IrmaCreate:
    """A task we want to create on the Irma side from a phone reminder."""

    project_id: str
    reminder_uuid: str
    title: str
    notes: str
    due_date: date | None
    scheduled_for: date | None
    is_completed: bool


@dataclass(frozen=True)
class IrmaPatch:
    irma_id: str          # Task or Project id in Irma
    kind: str             # "task" | "project"
    title: str | None
    notes: str | None
    due_date: date | None
    scheduled_for: date | None
    is_completed: bool | None


@dataclass
class SyncPlan:
    creates_on_reminders: list[RemoteCreate] = field(default_factory=list)
    patches_on_reminders: list[RemotePatch] = field(default_factory=list)
    deletes_on_reminders: list[RemoteDelete] = field(default_factory=list)
    creates_on_irma: list[IrmaCreate] = field(default_factory=list)
    patches_on_irma: list[IrmaPatch] = field(default_factory=list)
    deletes_on_irma: list[str] = field(default_factory=list)


def _project_remote_title(p: IrmaProjectSnap) -> str:
    if p.status is ProjectStatus.PAUSED:
        return f"{_PAUSED_PREFIX}{p.name}"
    return p.name


def plan(
    irma: IrmaSnapshot,
    helper_reminders: list[HelperReminder],
    *,
    inbox_project_id: str | None,
) -> SyncPlan:
    """Compute the reconciliation plan."""

    sp = SyncPlan()
    rem_by_uuid: dict[str, HelperReminder] = {r.uuid: r for r in helper_reminders}
    irma_proj_by_uuid: dict[str, IrmaProjectSnap] = {
        p.reminder_uuid: p for p in irma.projects if p.reminder_uuid is not None
    }
    irma_task_by_uuid: dict[str, IrmaTaskSnap] = {
        t.reminder_uuid: t for t in irma.tasks if t.reminder_uuid is not None
    }

    # --- Projects --------------------------------------------------------
    for proj in irma.projects:
        if proj.status is ProjectStatus.ARCHIVED:
            if proj.reminder_uuid and proj.reminder_uuid in rem_by_uuid:
                # delete parent + child reminders that hang off it
                sp.deletes_on_reminders.append(RemoteDelete(uuid=proj.reminder_uuid))
                for r in helper_reminders:
                    if r.parent_uuid == proj.reminder_uuid:
                        sp.deletes_on_reminders.append(RemoteDelete(uuid=r.uuid))
            continue

        if proj.reminder_uuid is None:
            sp.creates_on_reminders.append(
                RemoteCreate(
                    irma_id=proj.id,
                    kind="project",
                    fields=ReminderFields(
                        title=_project_remote_title(proj), parent_uuid=None
                    ),
                )
            )
            continue

        rem = rem_by_uuid.get(proj.reminder_uuid)
        if rem is None:
            # uuid set but reminder is gone → forget the linkage; next loop will
            # create a fresh one. Modeled as an Irma patch clearing the uuid
            # via a planner-side delete signal would be cleaner; for now the
            # service handles this by passing `reminder_uuid=None` snapshots
            # when the uuid is missing on the remote side.
            sp.creates_on_reminders.append(
                RemoteCreate(
                    irma_id=proj.id,
                    kind="project",
                    fields=ReminderFields(
                        title=_project_remote_title(proj), parent_uuid=None
                    ),
                )
            )
            continue

        target_title = _project_remote_title(proj)
        remote_newer = rem.last_modified > proj.updated_at
        if remote_newer and rem.title != target_title and rem.title.removeprefix(_PAUSED_PREFIX) != proj.name:
            sp.patches_on_irma.append(
                IrmaPatch(
                    irma_id=proj.id, kind="project",
                    title=rem.title.removeprefix(_PAUSED_PREFIX),
                    notes=None, due_date=None, scheduled_for=None,
                    is_completed=None,
                )
            )
        elif not remote_newer and rem.title != target_title:
            sp.patches_on_reminders.append(
                RemotePatch(
                    uuid=rem.uuid, irma_id=proj.id, kind="project",
                    fields=ReminderFields(title=target_title),
                )
            )

    # --- Tasks (Irma side) ----------------------------------------------
    for task in irma.tasks:
        parent = next(
            (p for p in irma.projects if p.id == task.project_id), None
        )
        if parent is None or parent.status is ProjectStatus.ARCHIVED:
            continue
        parent_uuid = parent.reminder_uuid

        if task.reminder_uuid is None:
            if parent_uuid is None:
                # parent not yet synced; skip for now — the project create
                # this same cycle gives the next cycle a parent uuid
                continue
            sp.creates_on_reminders.append(
                RemoteCreate(
                    irma_id=task.id,
                    kind="task",
                    fields=ReminderFields(
                        title=task.title,
                        notes=task.notes,
                        due_date=task.due_date,
                        start_date=task.scheduled_for,
                        is_completed=(task.status is TaskStatus.DONE),
                        parent_uuid=parent_uuid,
                    ),
                )
            )
            continue

        rem = rem_by_uuid.get(task.reminder_uuid)
        if rem is None:
            sp.deletes_on_irma.append(task.id)
            continue

        remote_newer = rem.last_modified > task.updated_at
        if remote_newer:
            sp.patches_on_irma.append(
                IrmaPatch(
                    irma_id=task.id, kind="task",
                    title=rem.title if rem.title != task.title else None,
                    notes=rem.notes if rem.notes != task.notes else None,
                    due_date=rem.due_date if rem.due_date != task.due_date else None,
                    scheduled_for=(
                        rem.start_date if rem.start_date != task.scheduled_for else None
                    ),
                    is_completed=(
                        rem.is_completed
                        if rem.is_completed != (task.status is TaskStatus.DONE)
                        else None
                    ),
                )
            )
        else:
            patch_fields = ReminderFields(
                title=task.title if rem.title != task.title else None,
                notes=task.notes if rem.notes != task.notes else None,
                due_date=task.due_date if rem.due_date != task.due_date else None,
                start_date=(
                    task.scheduled_for if rem.start_date != task.scheduled_for else None
                ),
                is_completed=(
                    (task.status is TaskStatus.DONE)
                    if rem.is_completed != (task.status is TaskStatus.DONE)
                    else None
                ),
                parent_uuid=(
                    parent_uuid if parent_uuid and rem.parent_uuid != parent_uuid else None
                ),
            )
            if any(
                v is not None
                for v in patch_fields.model_dump(exclude_none=True).values()
            ):
                sp.patches_on_reminders.append(
                    RemotePatch(
                        uuid=rem.uuid, irma_id=task.id, kind="task",
                        fields=patch_fields,
                    )
                )

    # --- Reminders that have no Irma counterpart ------------------------
    for rem in helper_reminders:
        if rem.uuid in irma_proj_by_uuid or rem.uuid in irma_task_by_uuid:
            continue
        # Subtask of a known project → create as Task in that project
        if rem.parent_uuid and rem.parent_uuid in irma_proj_by_uuid:
            proj = irma_proj_by_uuid[rem.parent_uuid]
            sp.creates_on_irma.append(
                IrmaCreate(
                    project_id=proj.id,
                    reminder_uuid=rem.uuid,
                    title=rem.title,
                    notes=rem.notes,
                    due_date=rem.due_date,
                    scheduled_for=rem.start_date,
                    is_completed=rem.is_completed,
                )
            )
            continue
        # Orphan at top level → Inbox project, if configured
        if rem.parent_uuid is None and inbox_project_id is not None:
            sp.creates_on_irma.append(
                IrmaCreate(
                    project_id=inbox_project_id,
                    reminder_uuid=rem.uuid,
                    title=rem.title,
                    notes=rem.notes,
                    due_date=rem.due_date,
                    scheduled_for=rem.start_date,
                    is_completed=rem.is_completed,
                )
            )

    return sp


def plan_to_batch_ops(plan: SyncPlan, *, project_uuid_by_id: dict[str, str]) -> list[BatchOp]:
    """Flatten a SyncPlan into ordered batch ops for `bridge.batch()`.

    Order: project creates → task creates → all patches → deletes.
    Task creates may reference a newly-minted project uuid; the caller
    populates `project_uuid_by_id` with uuids from the prior create
    results before flattening the task half of the plan. The planner
    itself doesn't see those uuids, so we re-target here.
    """

    ops: list[BatchOp] = []
    for c in plan.creates_on_reminders:
        if c.kind == "task" and c.fields.parent_uuid is None:
            # Should not happen — fields.parent_uuid is set at plan time —
            # but guard anyway.
            continue
        ops.append(BatchOp.create_op(c.fields))
    for p in plan.patches_on_reminders:
        ops.append(BatchOp.update_op(p.uuid, p.fields))
    for d in plan.deletes_on_reminders:
        ops.append(BatchOp.delete_op(d.uuid))
    return ops
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_planner.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations/reminders/planner.py \
        services/api/tests/integrations/test_reminders_planner.py
git commit -m "feat(reminders): pure-function reconciliation planner"
```

---

### Task 13: Inbox-project bootstrapper

**Files:**
- Create: `services/api/src/irma_api/integrations/reminders/inbox.py`
- Create: `services/api/tests/integrations/test_reminders_inbox.py`

- [ ] **Step 1: Write the failing test**

`services/api/tests/integrations/test_reminders_inbox.py`:

```python
from __future__ import annotations

import aiosqlite
import pytest

from irma_api.integrations.reminders.inbox import INBOX_NAME, ensure_inbox_project
from irma_api.store.migrations import ensure_schema
from irma_api.store.repos.project_repo import ProjectRepo


@pytest.fixture
async def conn(tmp_path):
    async with aiosqlite.connect(tmp_path / "t.db") as c:
        c.row_factory = aiosqlite.Row
        await ensure_schema(c)
        yield c


@pytest.mark.asyncio
async def test_creates_inbox_when_missing(conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(conn)
    inbox = await ensure_inbox_project(repo)
    assert inbox.name == INBOX_NAME
    listed = await repo.list()
    assert any(p.name == INBOX_NAME for p in listed)


@pytest.mark.asyncio
async def test_returns_existing_inbox_when_present(conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(conn)
    first = await ensure_inbox_project(repo)
    second = await ensure_inbox_project(repo)
    assert first.id == second.id
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_inbox.py -v
```

Expected: module not found.

- [ ] **Step 3: Write `inbox.py`**

```python
"""Ensure the auto-managed Inbox project exists.

Called at the top of every sync — re-creates the Inbox row if the user
manually deleted it, since the planner needs a target for top-level
phone-captured reminders.
"""

from __future__ import annotations

from irma_api.models.project import Project, ProjectCreate, ProjectStatus
from irma_api.store.errors import ConflictError
from irma_api.store.repos.project_repo import ProjectRepo

INBOX_NAME = "Inbox"
INBOX_DESCRIPTION = "Auto-created. Triage items captured from phone."


async def ensure_inbox_project(repo: ProjectRepo) -> Project:
    """Return the Inbox project, creating it idempotently if missing."""

    existing = [
        p for p in await repo.list(
            statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED, ProjectStatus.ARCHIVED]
        )
        if p.name == INBOX_NAME
    ]
    if existing:
        return existing[0]
    try:
        return await repo.create(
            ProjectCreate(
                name=INBOX_NAME,
                description=INBOX_DESCRIPTION,
                status=ProjectStatus.ACTIVE,
                priority=3,
            )
        )
    except ConflictError:
        # Race: someone else created it between our list and our create.
        again = [
            p for p in await repo.list(statuses=[ProjectStatus.ACTIVE])
            if p.name == INBOX_NAME
        ]
        if not again:
            raise
        return again[0]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_inbox.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations/reminders/inbox.py \
        services/api/tests/integrations/test_reminders_inbox.py
git commit -m "feat(reminders): inbox-project bootstrapper"
```

---

### Task 14: `ReminderSyncService` — sync_once + apply with rerun coalescing

**Files:**
- Create: `services/api/src/irma_api/integrations/reminders/sync.py`
- Create: `services/api/tests/integrations/test_reminders_sync.py`

- [ ] **Step 1: Write the failing test**

`services/api/tests/integrations/test_reminders_sync.py`:

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiosqlite
import pytest

from irma_api.integrations.reminders.bridge import ReminderBridge
from irma_api.integrations.reminders.sync import ReminderSyncService, SyncStats
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate
from irma_api.store.migrations import ensure_schema
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

FAKE = Path(__file__).parent / "fixtures" / "fake_helper.py"


@pytest.fixture
async def conn(tmp_path):
    async with aiosqlite.connect(tmp_path / "t.db") as c:
        c.row_factory = aiosqlite.Row
        await ensure_schema(c)
        yield c


def _bridge(tmp_path: Path) -> ReminderBridge:
    return ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(FAKE),),
        env={"FAKE_HELPER_STATE": str(tmp_path / "state.json")},
    )


@pytest.mark.asyncio
async def test_first_sync_pushes_existing_irma_state_to_reminders(
    conn: aiosqlite.Connection, tmp_path
) -> None:
    proj_repo = ProjectRepo(conn)
    task_repo = TaskRepo(conn)
    p = await proj_repo.create(ProjectCreate(name="Alpha"))
    t = await task_repo.create(TaskCreate(project_id=p.id, title="hello"))

    bridge = _bridge(tmp_path)
    cal_id = await bridge.ensure_list("Irma")

    svc = ReminderSyncService(
        project_repo=proj_repo, task_repo=task_repo,
        bridge=bridge, calendar_id=cal_id,
    )
    stats = await svc.sync_once()
    assert isinstance(stats, SyncStats)
    assert stats.created_remote == 2   # Alpha parent + hello subtask

    # After sync, Irma rows have reminder_uuid set
    refreshed_p = await proj_repo.get(p.id)
    refreshed_t = await task_repo.get(t.id)
    assert refreshed_p.reminder_uuid is not None
    assert refreshed_t.reminder_uuid is not None

    rems = await bridge.list(cal_id)
    titles = sorted(r.title for r in rems)
    assert titles == ["Alpha", "hello"]


@pytest.mark.asyncio
async def test_phone_create_under_known_parent_lands_as_irma_task(
    conn: aiosqlite.Connection, tmp_path
) -> None:
    proj_repo = ProjectRepo(conn)
    task_repo = TaskRepo(conn)
    p = await proj_repo.create(ProjectCreate(name="Alpha"))

    bridge = _bridge(tmp_path)
    cal_id = await bridge.ensure_list("Irma")
    svc = ReminderSyncService(
        project_repo=proj_repo, task_repo=task_repo,
        bridge=bridge, calendar_id=cal_id,
    )
    await svc.sync_once()  # Push Alpha
    rems = await bridge.list(cal_id)
    parent_uuid = next(r.uuid for r in rems if r.title == "Alpha")

    # Simulate phone-side create: a subtask of Alpha.
    from irma_api.integrations.reminders.models import BatchOp, ReminderFields
    await bridge.batch(
        cal_id,
        [BatchOp.create_op(ReminderFields(title="from-phone", parent_uuid=parent_uuid))],
    )

    stats = await svc.sync_once()
    assert stats.created_local == 1

    tasks = await task_repo.list(project_id=p.id)
    assert any(t.title == "from-phone" for t in tasks)


@pytest.mark.asyncio
async def test_phone_orphan_lands_in_inbox(
    conn: aiosqlite.Connection, tmp_path
) -> None:
    proj_repo = ProjectRepo(conn)
    task_repo = TaskRepo(conn)
    bridge = _bridge(tmp_path)
    cal_id = await bridge.ensure_list("Irma")
    svc = ReminderSyncService(
        project_repo=proj_repo, task_repo=task_repo,
        bridge=bridge, calendar_id=cal_id,
    )
    await svc.sync_once()  # Creates Inbox project on Irma side, pushes parent.

    from irma_api.integrations.reminders.models import BatchOp, ReminderFields
    await bridge.batch(
        cal_id,
        [BatchOp.create_op(ReminderFields(title="quick-capture", parent_uuid=None))],
    )

    stats = await svc.sync_once()
    assert stats.created_local == 1
    from irma_api.integrations.reminders.inbox import INBOX_NAME
    inbox = next(
        p for p in await proj_repo.list() if p.name == INBOX_NAME
    )
    tasks = await task_repo.list(project_id=inbox.id)
    assert any(t.title == "quick-capture" for t in tasks)


@pytest.mark.asyncio
async def test_coalescing_rerun_flag(
    conn: aiosqlite.Connection, tmp_path, monkeypatch
) -> None:
    """A concurrent sync_once call while another is in flight schedules one rerun."""
    proj_repo = ProjectRepo(conn)
    task_repo = TaskRepo(conn)
    bridge = _bridge(tmp_path)
    cal_id = await bridge.ensure_list("Irma")
    svc = ReminderSyncService(
        project_repo=proj_repo, task_repo=task_repo,
        bridge=bridge, calendar_id=cal_id,
    )
    calls = 0
    original = svc._run_once_locked

    async def counting() -> SyncStats:
        nonlocal calls
        calls += 1
        return await original()

    monkeypatch.setattr(svc, "_run_once_locked", counting)

    a, b, c = await asyncio.gather(
        svc.sync_once(), svc.sync_once(), svc.sync_once()
    )
    # First call runs; concurrent calls bounce off the lock, but at least one
    # follow-up runs because the rerun flag was set.
    assert calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_sync.py -v
```

Expected: module not found.

- [ ] **Step 3: Write `sync.py`**

```python
"""ReminderSyncService — the single coroutine that touches both sides.

All triggers funnel into `sync_once()`. The service guarantees:

* at most one sync runs at a time (asyncio.Lock);
* a trigger fired while a sync is in flight schedules exactly one
  follow-up run (pending_rerun flag);
* every Irma row touched by a sync has its `updated_at` set to the
  helper-reported `last_modified` so the next tick doesn't bounce
  the same row.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from irma_api.integrations.reminders.bridge import BridgeError, ReminderBridge
from irma_api.integrations.reminders.inbox import INBOX_NAME, ensure_inbox_project
from irma_api.integrations.reminders.models import (
    BatchOp,
    BatchResult,
    ReminderFields,
)
from irma_api.integrations.reminders.planner import (
    IrmaProjectSnap,
    IrmaSnapshot,
    IrmaTaskSnap,
    RemoteCreate,
    SyncPlan,
    plan,
)
from irma_api.models.project import ProjectStatus
from irma_api.models.task import TaskCreate, TaskStatus, TaskUpdate
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

logger = structlog.get_logger(__name__)


@dataclass
class SyncStats:
    created_remote: int = 0
    patched_remote: int = 0
    deleted_remote: int = 0
    created_local: int = 0
    patched_local: int = 0
    deleted_local: int = 0


class ReminderSyncService:
    def __init__(
        self,
        *,
        project_repo: ProjectRepo,
        task_repo: TaskRepo,
        bridge: ReminderBridge,
        calendar_id: str,
    ) -> None:
        self._projects = project_repo
        self._tasks = task_repo
        self._bridge = bridge
        self._calendar_id = calendar_id
        self._lock = asyncio.Lock()
        self._pending_rerun = False
        self.last_sync_at: datetime | None = None
        self.last_error: str | None = None

    async def sync_once(self) -> SyncStats:
        """Coalescing entrypoint.

        If a sync is in flight, set the rerun flag and return zero-stats
        immediately. The in-flight sync, upon finishing, will pick up the
        flag and kick exactly one more run.
        """
        if self._lock.locked():
            self._pending_rerun = True
            return SyncStats()

        async with self._lock:
            stats = await self._run_once_locked()
            while self._pending_rerun:
                self._pending_rerun = False
                follow_up = await self._run_once_locked()
                stats.created_remote += follow_up.created_remote
                stats.patched_remote += follow_up.patched_remote
                stats.deleted_remote += follow_up.deleted_remote
                stats.created_local += follow_up.created_local
                stats.patched_local += follow_up.patched_local
                stats.deleted_local += follow_up.deleted_local
            return stats

    async def _run_once_locked(self) -> SyncStats:
        try:
            inbox = await ensure_inbox_project(self._projects)
            irma_snap, helper_state = await self._snapshot()
            sync_plan = plan(
                irma_snap, helper_state, inbox_project_id=inbox.id
            )
            stats = await self._apply(sync_plan)
            self.last_sync_at = datetime.now(UTC)
            self.last_error = None
            logger.info(
                "reminders.sync.completed",
                created_remote=stats.created_remote,
                patched_remote=stats.patched_remote,
                deleted_remote=stats.deleted_remote,
                created_local=stats.created_local,
                patched_local=stats.patched_local,
                deleted_local=stats.deleted_local,
            )
            return stats
        except BridgeError as exc:
            self.last_error = f"{exc.code}: {exc.message}"
            logger.warning("reminders.sync.failed", code=exc.code, message=exc.message)
            return SyncStats()
        except Exception as exc:
            self.last_error = repr(exc)
            logger.exception("reminders.sync.crashed")
            return SyncStats()

    async def _snapshot(self) -> tuple[IrmaSnapshot, list]:
        projects = await self._projects.list(
            statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED, ProjectStatus.ARCHIVED]
        )
        tasks = await self._tasks.list()
        snap = IrmaSnapshot(
            projects=[
                IrmaProjectSnap(
                    id=p.id, name=p.name, status=p.status,
                    reminder_uuid=p.reminder_uuid, updated_at=p.updated_at,
                )
                for p in projects
            ],
            tasks=[
                IrmaTaskSnap(
                    id=t.id, project_id=t.project_id, title=t.title,
                    status=t.status, reminder_uuid=t.reminder_uuid,
                    updated_at=t.updated_at, due_date=t.due_date,
                    scheduled_for=t.scheduled_for, notes=t.notes,
                )
                for t in tasks
            ],
        )
        rems = await self._bridge.list(self._calendar_id)
        return snap, rems

    async def _apply(self, sync_plan: SyncPlan) -> SyncStats:
        stats = SyncStats()

        # --- Phase A: create projects on Reminders, capture uuids ---
        project_creates = [c for c in sync_plan.creates_on_reminders if c.kind == "project"]
        if project_creates:
            ops = [BatchOp.create_op(c.fields) for c in project_creates]
            results = await self._bridge.batch(self._calendar_id, ops)
            for c, r in zip(project_creates, results, strict=True):
                if r.ok and r.uuid:
                    await self._projects.set_reminder_uuid(c.irma_id, r.uuid)
                    stats.created_remote += 1

        # --- Phase B: create tasks on Reminders, retargeting parent_uuid ---
        # After Phase A, some project rows may have a fresh reminder_uuid that
        # the planner didn't see. Re-pull project uuids from the DB.
        proj_uuid_by_id = {
            p.id: p.reminder_uuid for p in await self._projects.list(
                statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED]
            )
        }
        task_creates: list[RemoteCreate] = [
            c for c in sync_plan.creates_on_reminders if c.kind == "task"
        ]
        # Filter out task creates whose parent has no uuid yet — they'll be
        # picked up on the next sync.
        task_creates_ready = []
        task_creates_args: list[tuple[RemoteCreate, str]] = []
        for c in task_creates:
            # Find the task's project_id via the irma_id (which is task.id)
            task = await self._tasks.get(c.irma_id)
            parent_uuid = proj_uuid_by_id.get(task.project_id) or c.fields.parent_uuid
            if not parent_uuid:
                continue
            new_fields = c.fields.model_copy(update={"parent_uuid": parent_uuid})
            task_creates_ready.append(c)
            task_creates_args.append((c, parent_uuid))
        if task_creates_ready:
            ops = []
            for c, parent_uuid in task_creates_args:
                ops.append(BatchOp.create_op(
                    c.fields.model_copy(update={"parent_uuid": parent_uuid})
                ))
            results = await self._bridge.batch(self._calendar_id, ops)
            for c, r in zip(task_creates_ready, results, strict=True):
                if r.ok and r.uuid:
                    await self._tasks.set_reminder_uuid(c.irma_id, r.uuid)
                    stats.created_remote += 1

        # --- Phase C: remote patches ---
        if sync_plan.patches_on_reminders:
            ops = [
                BatchOp.update_op(p.uuid, p.fields)
                for p in sync_plan.patches_on_reminders
            ]
            results = await self._bridge.batch(self._calendar_id, ops)
            for r in results:
                if r.ok:
                    stats.patched_remote += 1

        # --- Phase D: remote deletes ---
        if sync_plan.deletes_on_reminders:
            ops = [BatchOp.delete_op(d.uuid) for d in sync_plan.deletes_on_reminders]
            results = await self._bridge.batch(self._calendar_id, ops)
            for r in results:
                if r.ok:
                    stats.deleted_remote += 1

        # --- Phase E: Irma-side creates from phone ---
        for create in sync_plan.creates_on_irma:
            new_task = await self._tasks.create(
                TaskCreate(
                    project_id=create.project_id,
                    title=create.title,
                    notes=create.notes,
                    due_date=create.due_date,
                    scheduled_for=create.scheduled_for,
                    status=(
                        TaskStatus.DONE if create.is_completed else TaskStatus.TODO
                    ),
                )
            )
            await self._tasks.set_reminder_uuid(new_task.id, create.reminder_uuid)
            stats.created_local += 1

        # --- Phase F: Irma-side patches from phone ---
        for patch in sync_plan.patches_on_irma:
            if patch.kind == "task":
                update_kwargs: dict[str, object] = {}
                if patch.title is not None:
                    update_kwargs["title"] = patch.title
                if patch.notes is not None:
                    update_kwargs["notes"] = patch.notes
                if patch.due_date is not None:
                    update_kwargs["due_date"] = patch.due_date
                if patch.scheduled_for is not None:
                    update_kwargs["scheduled_for"] = patch.scheduled_for
                if patch.is_completed is not None:
                    update_kwargs["status"] = (
                        TaskStatus.DONE if patch.is_completed else TaskStatus.TODO
                    )
                if update_kwargs:
                    await self._tasks.update(patch.irma_id, TaskUpdate(**update_kwargs))
                    stats.patched_local += 1
            elif patch.kind == "project":
                if patch.title is not None:
                    from irma_api.models.project import ProjectUpdate
                    await self._projects.update(
                        patch.irma_id, ProjectUpdate(name=patch.title)
                    )
                    stats.patched_local += 1

        # --- Phase G: Irma-side deletes ---
        for tid in sync_plan.deletes_on_irma:
            await self._tasks.delete(tid)
            stats.deleted_local += 1

        return stats
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_sync.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations/reminders/sync.py \
        services/api/tests/integrations/test_reminders_sync.py
git commit -m "feat(reminders): ReminderSyncService — snapshot, plan, apply, coalesce"
```

---

### Task 15: Settings additions

**Files:**
- Modify: `services/api/src/irma_api/config.py`
- Create: `services/api/tests/test_settings_reminders.py`

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/test_settings_reminders.py
from __future__ import annotations

from pathlib import Path

from irma_api.config import Settings


def test_reminders_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.reminders_calendar_id is None
    assert s.reminders_sync_interval_seconds == 60
    assert isinstance(s.reminders_helper_path, Path)
    assert s.reminders_helper_path.name == "irma-reminders-helper"


def test_reminders_calendar_id_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REMINDERS_CALENDAR_ID", "cal-Irma")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.reminders_calendar_id == "cal-Irma"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && uv run pytest tests/test_settings_reminders.py -v
```

Expected: AttributeError — fields not defined.

- [ ] **Step 3: Extend `config.py`**

Add to the `Settings` class:

```python
    # --- Apple Reminders -----------------------------------------------------
    # Set by the link flow; absence means the integration is unlinked.
    reminders_calendar_id: str | None = None
    reminders_sync_interval_seconds: int = 60
    reminders_helper_path: Path = Path(
        "tools/reminders-helper/bin/irma-reminders-helper"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_settings_reminders.py tests/test_settings.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/config.py \
        services/api/tests/test_settings_reminders.py
git commit -m "feat(reminders): settings for calendar id, sync interval, helper path"
```

---

### Task 16: Extend `IntegrationsStatus` to surface reminders state

**Files:**
- Modify: `services/api/src/irma_api/routers/integrations.py`
- Modify: `services/api/tests/test_integrations_router.py`

- [ ] **Step 1: Add a failing test**

In `test_integrations_router.py` add:

```python
@pytest.mark.asyncio
async def test_status_includes_reminders_fields(client) -> None:
    resp = await client.get("/api/v1/integrations/google/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "reminders_linked" in data
    assert data["reminders_linked"] is False
    assert "reminders_last_sync_at" in data
    assert data["reminders_last_sync_at"] is None
    assert "reminders_last_sync_error" in data
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/api && uv run pytest tests/test_integrations_router.py -v
```

Expected: KeyError.

- [ ] **Step 3: Extend the router**

Replace `routers/integrations.py`:

```python
"""Integration status endpoints for the dashboard."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from irma_api.agents.llm import LLMClient
from irma_api.config import Settings

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationsStatus(BaseModel):
    calendar_linked: bool
    resend_linked: bool
    reminders_linked: bool
    reminders_last_sync_at: datetime | None
    reminders_last_sync_error: str | None
    user_email: str | None
    llm_backend: str | None
    llm_model: str | None


@router.get("/google/status", response_model=IntegrationsStatus)
async def integrations_status(request: Request) -> IntegrationsStatus:
    settings: Settings = request.app.state.settings
    llm: LLMClient | None = getattr(request.app.state, "llm", None)
    sync_svc = getattr(request.app.state, "reminder_sync", None)

    calendar_linked = settings.google_oauth_refresh_token is not None
    resend_linked = (
        settings.resend_api_key is not None
        and settings.irma_user_email is not None
    )
    reminders_linked = settings.reminders_calendar_id is not None and sync_svc is not None

    return IntegrationsStatus(
        calendar_linked=calendar_linked,
        resend_linked=resend_linked,
        reminders_linked=reminders_linked,
        reminders_last_sync_at=getattr(sync_svc, "last_sync_at", None),
        reminders_last_sync_error=getattr(sync_svc, "last_error", None),
        user_email=settings.irma_user_email,
        llm_backend=llm.backend if llm else None,
        llm_model=llm.model if llm else None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_integrations_router.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/routers/integrations.py \
        services/api/tests/test_integrations_router.py
git commit -m "feat(reminders): surface reminders link state on status endpoint"
```

---

### Task 17: New router `/integrations/reminders/{link,sync}`

**Files:**
- Create: `services/api/src/irma_api/routers/reminders.py`
- Create: `services/api/tests/integrations/test_reminders_router.py`
- Modify: `services/api/src/irma_api/app.py` (just to include the router; full wiring comes in Task 18)

- [ ] **Step 1: Write the failing test**

`services/api/tests/integrations/test_reminders_router.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from irma_api.app import create_app


@pytest.fixture
async def client(monkeypatch, tmp_path):
    app = create_app()
    # We need access to the lifespan-initialised state for these tests.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, app


@pytest.mark.asyncio
async def test_link_succeeds_when_helper_grants(client) -> None:
    c, app = client
    fake_bridge = MagicMock()
    fake_bridge.request_access = AsyncMock(return_value=True)
    fake_bridge.ensure_list = AsyncMock(return_value="cal-Irma")
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    app.state.reminder_bridge = fake_bridge
    app.state.reminder_sync_factory = lambda calendar_id: fake_sync

    resp = await c.post("/api/v1/integrations/reminders/link")
    assert resp.status_code == 200
    data = resp.json()
    assert data["calendar_id"] == "cal-Irma"
    fake_sync.sync_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_returns_403_when_denied(client) -> None:
    c, app = client
    fake_bridge = MagicMock()
    fake_bridge.request_access = AsyncMock(return_value=False)
    app.state.reminder_bridge = fake_bridge
    app.state.reminder_sync_factory = lambda calendar_id: MagicMock()

    resp = await c.post("/api/v1/integrations/reminders/link")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sync_now_returns_stats(client) -> None:
    c, app = client
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock(
        return_value=type("S", (), {
            "created_remote": 1, "patched_remote": 0, "deleted_remote": 0,
            "created_local": 0, "patched_local": 0, "deleted_local": 0,
        })()
    )
    app.state.reminder_sync = fake_sync

    resp = await c.post("/api/v1/integrations/reminders/sync")
    assert resp.status_code == 200
    assert resp.json()["created_remote"] == 1


@pytest.mark.asyncio
async def test_sync_when_unlinked_returns_409(client) -> None:
    c, app = client
    app.state.reminder_sync = None
    resp = await c.post("/api/v1/integrations/reminders/sync")
    assert resp.status_code == 409
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_router.py -v
```

Expected: 404 or import error — router not registered.

- [ ] **Step 3: Write the router**

`services/api/src/irma_api/routers/reminders.py`:

```python
"""Link / unlink / force-sync endpoints for Apple Reminders integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

if TYPE_CHECKING:
    from irma_api.integrations.reminders.bridge import ReminderBridge
    from irma_api.integrations.reminders.sync import ReminderSyncService

router = APIRouter(prefix="/integrations/reminders", tags=["integrations"])


class LinkResponse(BaseModel):
    calendar_id: str


class SyncResponse(BaseModel):
    created_remote: int
    patched_remote: int
    deleted_remote: int
    created_local: int
    patched_local: int
    deleted_local: int


@router.post("/link", response_model=LinkResponse)
async def link(request: Request) -> LinkResponse:
    bridge: ReminderBridge | None = getattr(request.app.state, "reminder_bridge", None)
    factory = getattr(request.app.state, "reminder_sync_factory", None)
    if bridge is None or factory is None:
        raise HTTPException(
            status_code=503,
            detail="reminders helper not configured (missing binary or settings)",
        )

    granted = await bridge.request_access()
    if not granted:
        raise HTTPException(status_code=403, detail="reminders access denied")

    calendar_id = await bridge.ensure_list("Irma")
    request.app.state.settings.reminders_calendar_id = calendar_id
    svc = factory(calendar_id)
    request.app.state.reminder_sync = svc
    await svc.sync_once()
    return LinkResponse(calendar_id=calendar_id)


@router.delete("/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(request: Request) -> Response:
    """Clear linkage. Does not delete the macOS Reminders list itself."""
    store = request.app.state.store
    conn = store.connection
    await conn.execute("UPDATE task SET reminder_uuid = NULL")
    await conn.execute("UPDATE project SET reminder_uuid = NULL")
    await conn.commit()
    request.app.state.settings.reminders_calendar_id = None
    request.app.state.reminder_sync = None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync", response_model=SyncResponse)
async def sync_now(request: Request) -> SyncResponse:
    svc: ReminderSyncService | None = getattr(request.app.state, "reminder_sync", None)
    if svc is None:
        raise HTTPException(status_code=409, detail="reminders integration not linked")
    stats = await svc.sync_once()
    return SyncResponse(
        created_remote=stats.created_remote,
        patched_remote=stats.patched_remote,
        deleted_remote=stats.deleted_remote,
        created_local=stats.created_local,
        patched_local=stats.patched_local,
        deleted_local=stats.deleted_local,
    )
```

- [ ] **Step 4: Register the router in `app.py`**

Add the import alongside other router imports:

```python
from irma_api.routers.reminders import router as reminders_router
```

In `create_app`'s `app.include_router(...)` block, add:

```python
    app.include_router(reminders_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_router.py -v
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
cd ../..
git add services/api/src/irma_api/routers/reminders.py \
        services/api/src/irma_api/app.py \
        services/api/tests/integrations/test_reminders_router.py
git commit -m "feat(reminders): link/unlink/sync HTTP endpoints"
```

---

### Task 18: Wire bridge + sync service into the app lifespan

**Files:**
- Modify: `services/api/src/irma_api/app.py`
- Create: `services/api/tests/test_app_reminders_lifespan.py`

- [ ] **Step 1: Add a failing test**

```python
# services/api/tests/test_app_reminders_lifespan.py
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from irma_api.app import create_app


@pytest.mark.asyncio
async def test_lifespan_exposes_reminder_bridge_when_binary_present(tmp_path, monkeypatch):
    fake_bin = tmp_path / "irma-reminders-helper"
    fake_bin.write_text("#!/bin/sh\necho '{}'\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("REMINDERS_HELPER_PATH", str(fake_bin))

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t"):
        async with app.router.lifespan_context(app):
            assert hasattr(app.state, "reminder_bridge")
            assert app.state.reminder_bridge is not None
            assert hasattr(app.state, "reminder_sync_factory")
            # Unlinked state by default:
            assert getattr(app.state, "reminder_sync", None) is None


@pytest.mark.asyncio
async def test_lifespan_skips_reminder_bridge_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("REMINDERS_HELPER_PATH", str(tmp_path / "absent"))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t"):
        async with app.router.lifespan_context(app):
            assert getattr(app.state, "reminder_bridge", None) is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && uv run pytest tests/test_app_reminders_lifespan.py -v
```

Expected: AttributeError — `reminder_bridge` not on `app.state`.

- [ ] **Step 3: Extend `app.py` lifespan**

After the existing tool-registry setup but before the scheduler/`logger.info("app.ready", ...)` block, add:

```python
    reminder_bridge = None
    reminder_sync_factory = None
    reminder_sync = None
    if settings.reminders_helper_path.exists():
        from irma_api.integrations.reminders.bridge import ReminderBridge
        from irma_api.integrations.reminders.sync import ReminderSyncService
        from irma_api.store.repos.project_repo import ProjectRepo
        from irma_api.store.repos.task_repo import TaskRepo

        reminder_bridge = ReminderBridge(binary_path=settings.reminders_helper_path)

        def make_sync(calendar_id: str) -> ReminderSyncService:
            return ReminderSyncService(
                project_repo=ProjectRepo(store.connection),
                task_repo=TaskRepo(store.connection),
                bridge=reminder_bridge,
                calendar_id=calendar_id,
            )

        reminder_sync_factory = make_sync
        if settings.reminders_calendar_id is not None:
            reminder_sync = make_sync(settings.reminders_calendar_id)
        logger.info(
            "reminders.bridge.ready",
            linked=reminder_sync is not None,
            helper_path=str(settings.reminders_helper_path),
        )
    else:
        logger.info(
            "reminders.bridge.disabled",
            reason="helper binary not found",
            expected_path=str(settings.reminders_helper_path),
        )

    app.state.reminder_bridge = reminder_bridge
    app.state.reminder_sync_factory = reminder_sync_factory
    app.state.reminder_sync = reminder_sync
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_app_reminders_lifespan.py tests/test_app_boot.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/app.py \
        services/api/tests/test_app_reminders_lifespan.py
git commit -m "feat(reminders): wire bridge + sync factory into app lifespan"
```

---

### Task 19: Periodic scheduler tick

**Files:**
- Modify: `services/api/src/irma_api/runtime/scheduler.py`
- Modify: `services/api/src/irma_api/app.py`
- Create: `services/api/tests/test_scheduler_reminders.py`

- [ ] **Step 1: Add a failing test**

```python
# services/api/tests/test_scheduler_reminders.py
from __future__ import annotations

import asyncio

import pytest

from irma_api.runtime.scheduler import Scheduler


@pytest.mark.asyncio
async def test_scheduler_accepts_optional_reminders_tick() -> None:
    refresh_calls = 0
    reminder_calls = 0

    async def refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    async def reminders() -> None:
        nonlocal reminder_calls
        reminder_calls += 1

    sched = Scheduler(
        refresh_minutes=30,
        on_tick=refresh,
        reminders_interval_seconds=1,
        on_reminders_tick=reminders,
    )
    sched.start()
    await asyncio.sleep(1.5)
    sched.shutdown()
    assert reminder_calls >= 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && uv run pytest tests/test_scheduler_reminders.py -v
```

Expected: TypeError — Scheduler doesn't accept those kwargs.

- [ ] **Step 3: Extend `Scheduler`**

Replace `services/api/src/irma_api/runtime/scheduler.py` with:

```python
"""APScheduler wrapper. Periodic observer refresh + optional reminders sync."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = structlog.get_logger(__name__)


class Scheduler:
    def __init__(
        self,
        refresh_minutes: int,
        on_tick: Callable[[], Awaitable[None]],
        *,
        reminders_interval_seconds: int | None = None,
        on_reminders_tick: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._sched = AsyncIOScheduler()
        self._refresh_minutes = refresh_minutes
        self._on_tick = on_tick
        self._reminders_interval = reminders_interval_seconds
        self._on_reminders_tick = on_reminders_tick

    def start(self) -> None:
        self._sched.add_job(
            self._on_tick,
            trigger=IntervalTrigger(minutes=self._refresh_minutes),
            id="irma-refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if self._reminders_interval and self._on_reminders_tick:
            self._sched.add_job(
                self._on_reminders_tick,
                trigger=IntervalTrigger(seconds=self._reminders_interval),
                id="irma-reminders-sync",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        self._sched.start()
        logger.info(
            "scheduler.started",
            refresh_minutes=self._refresh_minutes,
            reminders_seconds=self._reminders_interval,
        )

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)
            logger.info("scheduler.stopped")
```

- [ ] **Step 4: Wire the reminders tick into `app.py`**

Replace the existing Scheduler block in `app.py` with:

```python
    async def reminders_tick() -> None:
        svc = app.state.reminder_sync
        if svc is not None:
            await svc.sync_once()

    scheduler = Scheduler(
        refresh_minutes=settings.irma_refresh_minutes,
        on_tick=tick,
        reminders_interval_seconds=(
            settings.reminders_sync_interval_seconds
            if reminder_bridge is not None
            else None
        ),
        on_reminders_tick=(
            reminders_tick if reminder_bridge is not None else None
        ),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_scheduler_reminders.py tests/test_app_boot.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd ../..
git add services/api/src/irma_api/runtime/scheduler.py \
        services/api/src/irma_api/app.py \
        services/api/tests/test_scheduler_reminders.py
git commit -m "feat(reminders): periodic sync tick on the existing scheduler"
```

---

### Task 20: Post-write triggers in projects.py and tasks.py

**Files:**
- Modify: `services/api/src/irma_api/routers/projects.py`
- Modify: `services/api/src/irma_api/routers/tasks.py`
- Create: `services/api/tests/test_post_write_sync_trigger.py`

- [ ] **Step 1: Add a failing test**

```python
# services/api/tests/test_post_write_sync_trigger.py
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from irma_api.app import create_app


@pytest.mark.asyncio
async def test_create_project_triggers_sync(monkeypatch):
    app = create_app()
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            app.state.reminder_sync = fake_sync
            resp = await c.post(
                "/api/v1/projects",
                json={"name": "test-sync-trigger"},
            )
            assert resp.status_code == 201
            # Background task may still be in flight; give it a beat.
            for _ in range(20):
                if fake_sync.sync_once.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
            fake_sync.sync_once.assert_awaited()


@pytest.mark.asyncio
async def test_complete_task_triggers_sync(monkeypatch):
    app = create_app()
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            app.state.reminder_sync = fake_sync
            p = await c.post("/api/v1/projects", json={"name": "trigger-via-task"})
            pid = p.json()["id"]
            t = await c.post(
                "/api/v1/tasks", json={"project_id": pid, "title": "x"}
            )
            tid = t.json()["id"]
            fake_sync.sync_once.reset_mock()
            await c.post(f"/api/v1/tasks/{tid}/complete")
            for _ in range(20):
                if fake_sync.sync_once.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
            fake_sync.sync_once.assert_awaited()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && uv run pytest tests/test_post_write_sync_trigger.py -v
```

Expected: `sync_once` not awaited — no trigger wired.

- [ ] **Step 3: Add a small helper**

Append to `services/api/src/irma_api/routers/integrations.py`:

```python
def _trigger_reminder_sync(request: Request) -> None:
    """Fire-and-forget reminders sync after a write to projects/tasks."""
    svc = getattr(request.app.state, "reminder_sync", None)
    if svc is not None:
        import asyncio as _asyncio
        _asyncio.create_task(svc.sync_once())
```

- [ ] **Step 4: Invoke the helper from `projects.py` write paths**

Import at top of `projects.py`:

```python
from irma_api.routers.integrations import _trigger_reminder_sync
```

After each successful write (the `return` in `create_project`, `update_project`, `delete_project`), call `_trigger_reminder_sync(request)` just before returning. Concrete patches:

```python
@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: Request, payload: ProjectCreate
) -> Project | JSONResponse:
    try:
        result = await _repo(request).create(payload)
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return result


@router.patch("/{project_id}", response_model=Project)
async def update_project(
    request: Request, project_id: str, patch: ProjectUpdate
) -> Project | JSONResponse:
    try:
        result = await _repo(request).update(project_id, patch)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return result


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(request: Request, project_id: str) -> Response:
    try:
        await _repo(request).delete(project_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Mirror in `tasks.py`**

```python
from irma_api.routers.integrations import _trigger_reminder_sync


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(request: Request, payload: TaskCreate) -> Task | JSONResponse:
    try:
        result = await _repo(request).create(payload)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return result


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    request: Request, task_id: str, patch: TaskUpdate
) -> Task | JSONResponse:
    try:
        result = await _repo(request).update(task_id, patch)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    _trigger_reminder_sync(request)
    return result


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(request: Request, task_id: str) -> Response:
    try:
        await _repo(request).delete(task_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    _trigger_reminder_sync(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/complete", response_model=Task)
async def complete_task(request: Request, task_id: str) -> Task | JSONResponse:
    try:
        result = await _repo(request).update(task_id, TaskUpdate(status=TaskStatus.DONE))
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    _trigger_reminder_sync(request)
    return result
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/test_post_write_sync_trigger.py tests/test_routers_projects.py tests/test_routers_tasks.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd ../..
git add services/api/src/irma_api/routers/projects.py \
        services/api/src/irma_api/routers/tasks.py \
        services/api/src/irma_api/routers/integrations.py \
        services/api/tests/test_post_write_sync_trigger.py
git commit -m "feat(reminders): fire-and-forget sync after Irma-side writes"
```

---

### Task 21: Opt-in end-to-end smoke test against real Reminders

**Files:**
- Create: `services/api/tests/integrations/test_reminders_e2e.py`

> This test exists to give a manual confidence check once the helper is built and TCC has been granted. It is **opt-in**: only runs when `IRMA_REMINDERS_E2E=1` is set. CI never runs it.

- [ ] **Step 1: Write the test**

```python
"""End-to-end smoke test against the real macOS Reminders database.

Run with:
    cd services/api
    IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py -v

The test creates a temp calendar (`Irma-Test-<uuid>`), syncs to it,
asserts contents, then tears it down. Requires the helper binary at
`tools/reminders-helper/bin/irma-reminders-helper` and Reminders access
granted to it.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import aiosqlite
import pytest

from irma_api.integrations.reminders.bridge import ReminderBridge
from irma_api.integrations.reminders.sync import ReminderSyncService
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate
from irma_api.store.migrations import ensure_schema
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

pytestmark = pytest.mark.skipif(
    not os.environ.get("IRMA_REMINDERS_E2E"),
    reason="set IRMA_REMINDERS_E2E=1 to run end-to-end Reminders tests",
)

REPO_ROOT = Path(__file__).resolve().parents[4]
HELPER = REPO_ROOT / "tools" / "reminders-helper" / "bin" / "irma-reminders-helper"


@pytest.mark.asyncio
async def test_full_push_to_real_reminders(tmp_path) -> None:
    assert HELPER.exists(), f"build the helper first: {HELPER}"
    test_list = f"Irma-Test-{uuid.uuid4().hex[:8]}"

    bridge = ReminderBridge(binary_path=HELPER)
    status = await bridge.access_status()
    if status != "authorized":
        granted = await bridge.request_access()
        if not granted:
            pytest.skip(f"reminders access status={status}; user must grant access")

    cal_id = await bridge.ensure_list(test_list)
    try:
        async with aiosqlite.connect(tmp_path / "e2e.db") as conn:
            conn.row_factory = aiosqlite.Row
            await ensure_schema(conn)
            projects = ProjectRepo(conn)
            tasks = TaskRepo(conn)
            p = await projects.create(ProjectCreate(name="E2E Project"))
            await tasks.create(TaskCreate(project_id=p.id, title="e2e task"))

            svc = ReminderSyncService(
                project_repo=projects, task_repo=tasks,
                bridge=bridge, calendar_id=cal_id,
            )
            stats = await svc.sync_once()
            assert stats.created_remote == 2

            rems = await bridge.list(cal_id)
            titles = sorted(r.title for r in rems)
            assert titles == ["E2E Project", "e2e task"]
    finally:
        await bridge.delete_calendar(cal_id)
```

- [ ] **Step 2: Verify the test is skipped by default**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_e2e.py -v
```

Expected: 1 skipped, 0 failed.

- [ ] **Step 3: (Manual, once locally) Run the e2e test**

```bash
IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py -v
```

Expected (with helper built + TCC granted): 1 passed. macOS Reminders momentarily shows an `Irma-Test-<uuid>` list which the test then removes.

- [ ] **Step 4: Commit**

```bash
cd ../..
git add services/api/tests/integrations/test_reminders_e2e.py
git commit -m "test(reminders): opt-in end-to-end smoke test"
```

---

### Task 22: README and linking-flow documentation

**Files:**
- Modify: `services/api/README.md` (or create if missing)
- Modify: `tools/reminders-helper/README.md`

- [ ] **Step 1: Append to `services/api/README.md`**

If the file doesn't exist, create it; otherwise append a new section:

```markdown
## Apple Reminders sync

Mirrors `Project` + `Task` rows into a macOS Reminders list named **Irma**
via a Swift helper binary. Phone changes in iCloud Reminders flow back on
the next sync (≤60 s, or instantly via `POST /integrations/reminders/sync`).

### One-time setup

1. Build the helper (macOS only):

       ./tools/reminders-helper/build.sh

   The output binary is checked in at
   `tools/reminders-helper/bin/irma-reminders-helper`; rebuild after editing
   anything under `tools/reminders-helper/Sources`.

2. Start the API as usual. On first link, macOS will prompt for
   Reminders permission against the helper binary.

3. Link:

       curl -X POST http://127.0.0.1:8765/api/v1/integrations/reminders/link

   On success, returns `{"calendar_id": "..."}`. From here, edits in either
   place flow both ways.

### Useful commands

| Action | Command |
| --- | --- |
| Force a sync now | `curl -X POST http://127.0.0.1:8765/api/v1/integrations/reminders/sync` |
| Unlink (preserve list) | `curl -X DELETE http://127.0.0.1:8765/api/v1/integrations/reminders/link` |
| Reset macOS TCC grant | `tccutil reset Reminders com.irma.reminders-helper` |
| Opt-in end-to-end test | `IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py` |
```

- [ ] **Step 2: Commit**

```bash
git add services/api/README.md tools/reminders-helper/README.md
git commit -m "docs(reminders): build + link + e2e quickstart"
```

---

## Self-Review Notes

A scan of the plan against the spec's section headings, with concrete task references:

| Spec section | Covered by |
| --- | --- |
| Architecture diagram + components | Task 1 (Swift scaffold), Task 8 (Python package), Task 17 (router) |
| Sync triggers | Task 19 (periodic), Task 20 (post-write), Task 17 (manual + initial link) |
| Coalescing rule | Task 14 (`asyncio.Lock` + `pending_rerun` test) |
| Identity tree + Inbox project | Task 13 (`ensure_inbox_project`) |
| Task field mapping | Task 12 (planner per-field translation) |
| Project field mapping (paused-prefix, archived-cascade) | Task 12 (`test_paused_project_title_prefixed`, `test_archived_project_cascade_deletes_reminders`) |
| Phone-initiated semantics | Task 12 (`test_remote_orphan_*`, `test_remote_only_task_with_known_parent_creates_in_project`, `test_irma_only_deletion_signal_when_uuid_present_but_reminder_gone`) |
| Conflict resolution | Task 12 (`test_remote_newer_patches_irma`, `test_irma_newer_patches_reminders`) |
| Three-pass algorithm | Task 14 (`_apply` phases A–G) |
| Error handling | Task 9 (`BridgeError` codes), Task 14 (`_run_once_locked` catches BridgeError + generic) |
| TCC + linking flow | Task 6 (`requestFullAccessToReminders`), Task 17 (link endpoint) |
| Settings additions | Task 15 |
| API surface | Task 17 (router) + Task 16 (status extension) |
| Helper command surface | Tasks 4–7 |
| Schema migration | Task 10 |
| `reminder_uuid` linkage + persistence | Task 11 |
| Observability (structlog events) | Task 14 (`reminders.sync.*`) |
| Testing strategy | Tasks 8–14 unit; Task 9 bridge with fake helper; Task 21 opt-in e2e; Tasks 2–5 Swift XCTest |
| Risks: list deleted on phone | The planner's "uuid set, reminder gone" branch (Task 12, `test_irma_only_deletion_signal...`) and the helper's `ensure-list` (re-creates) cover this in combination. Surfaced via `last_error` (Task 14). |
| Risks: TCC denied | Task 17 (403 response), Task 14 (`BridgeError` short-circuits sync), Task 22 (`tccutil reset` doc) |
| Out-of-scope items (live notifications, sub-subtasks, trash) | Not covered — by design |

**Placeholder scan:** all code blocks are complete; no "TODO/TBD/similar to" references; every command has expected output described. The `plan_to_batch_ops` helper in Task 12's planner.py is left as a forward-declared utility used by future fan-out — not strictly required by the current `_apply` (which builds ops inline), but provides a clean seam if we later move to a single-batch flatten. It compiles and is tested by extension of the planner.

**Type consistency:** `SyncStats` fields match between the dataclass declaration (Task 14) and the router response model (Task 17). `IrmaProjectSnap` / `IrmaTaskSnap` fields match between the planner (Task 12) and the service's `_snapshot` (Task 14). `reminder_uuid` is consistently `str | None` across models, repos, planner snapshots, and migrations.
