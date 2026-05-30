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

## Amendment 2026-05-30 (afternoon): one Reminders list per Project

**Reason:** the original plan mapped Project → parent reminder, Task → subtask of project. Verification against public EventKit headers (macOS 15.x / 26.x SDKs) confirmed there is no public `parentReminder` / subtask API — Apple's Reminders.app uses a private framework extension. Spec was amended (commit `7ad1abd`); Swift helper was refit (commit `d9e74ad`).

**New architecture:** each Project maps to its own `EKCalendar` named `Irma · <ProjectName>`. The Inbox is `Irma · Inbox`. Tasks are flat reminders within their project's calendar. Calendar discovery is a new helper command `list-calendars --prefix "Irma · "`; rename and delete are also calendar-level operations.

**Per-task effects** (see inline amendment notes in each task section below):

- **Task 6 (EventKitRemindersClient)** — already implemented under the new spec in commit `d9e74ad`, alongside `Models.swift` / `RemindersClient.swift` / `CommandHandler.swift` updates (drop `parent_uuid`, add `listCalendars` and `renameCalendar`). This task is **complete**; subagents should skip ahead to Task 7.
- **Task 7** — unaffected; main.swift dispatches all commands generically.
- **Task 8 (Python DTOs)** — drop `parent_uuid` from `HelperReminder` and `ReminderFields`. Add Pydantic `CalendarSummary` mirroring the Swift type.
- **Task 9 (Bridge + fake helper)** — add `list_calendars(prefix)` and `rename_calendar(calendar_id, title)` to `ReminderBridge`. Fake helper supports the two new commands.
- **Task 10 (Schema migration)** — Project column is **`reminder_calendar_id`** (an `EKCalendar.calendarIdentifier`), NOT `reminder_uuid`. Task still gets `reminder_uuid` (an `EKReminder.calendarItemIdentifier`).
- **Task 11 (Models + repos)** — Project model gains `reminder_calendar_id: str | None`. `ProjectRepo.set_reminder_calendar_id(...)`. Task model gains `reminder_uuid: str | None` (unchanged).
- **Task 12 (Planner)** — fundamentally rewritten. The pure function is now `plan(irma_snapshot, helper_state) -> SyncPlan` where `helper_state` is a dict keyed by calendar uuid → list of reminders, plus a separate map of calendar uuid → title. Output includes calendar-level operations (`create_calendar`, `rename_calendar`, `delete_calendar`) in addition to per-reminder ones. See the rewritten task body below.
- **Task 13 (Inbox bootstrapper)** — unchanged (still ensures the Inbox `Project` row).
- **Task 14 (SyncService)** — `_apply` rewritten as a four-pass algorithm (calendar reconcile → per-project snapshot → per-project reminder reconcile → apply). See the rewritten task body below.
- **Task 15 (Settings)** — drop `reminders_calendar_id`. Add `reminders_linked: bool = False` and `reminders_calendar_prefix: str = "Irma · "`.
- **Task 17 (Router)** — link flow no longer calls `ensure-list --name Irma`. Just `request-access`, set `reminders_linked=true`, trigger `sync_once()`. Unlink clears `reminder_calendar_id` (projects) and `reminder_uuid` (tasks).
- **Task 21 (E2E test)** — creates per-project test calendars; tears down by deleting them.
- **Task 22 (README)** — describes the `Irma · <Project>` naming convention.

Tasks not listed (16, 18, 19, 20) are architecturally unaffected.

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

> **Amendment 2026-05-30 (afternoon):** drop `parent_uuid` from both `HelperReminder` and `ReminderFields` (Swift side no longer carries it after the architectural pivot). Add a `CalendarSummary` Pydantic class mirroring the Swift type — `ReminderBridge.list_calendars` (Task 9) returns a list of these.

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
    CalendarSummary,
    HelperReminder,
    ReminderFields,
)


def test_helper_reminder_parses_helper_json() -> None:
    raw = {
        "uuid": "U-1",
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
    op = BatchOp.create_op(ReminderFields(title="hello"))
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
            "title": "x",
            "notes": "",
            "due_date": "not-a-date",
            "start_date": None,
            "is_completed": False,
            "completion_date": None,
            "last_modified": "2026-05-30T10:00:00Z",
        })


def test_calendar_summary_parses() -> None:
    raw = {"calendar_id": "CAL-1", "title": "Irma · Inbox"}
    cs = CalendarSummary.model_validate(raw)
    assert cs.calendar_id == "CAL-1"
    assert cs.title == "Irma · Inbox"
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


class CalendarSummary(BaseModel):
    """One calendar entry from `helper list-calendars`."""

    model_config = ConfigDict(populate_by_name=True)

    calendar_id: str
    title: str


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

> **Amendment 2026-05-30 (afternoon):** add two new bridge methods and matching fake-helper commands:
>
> - `ReminderBridge.list_calendars(prefix: str) -> list[CalendarSummary]` → calls `helper list-calendars --prefix <s>`.
> - `ReminderBridge.rename_calendar(calendar_id: str, title: str) -> bool` → calls `helper rename-calendar --calendar-id <s> --title <s>`.
>
> Pattern follows existing methods: use `_invoke_json`, parse the result. The fake helper script gains two corresponding handlers (`cmd_list_calendars`, `cmd_rename_calendar`) and an in-memory `lists` dict that supports prefix filtering and rename. Add two new bridge tests: `test_list_calendars_filters_by_prefix` and `test_rename_calendar_updates_title`.
>
> Drop `parent_uuid` from every reference in this task (test inputs, fake helper, bridge code) — per Task 8 amendment the field no longer exists.

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

### Task 10: Schema migration for reminder linkage columns

> **Amendment 2026-05-30 (afternoon):** Task gets `reminder_uuid TEXT` (an `EKReminder.calendarItemIdentifier`). Project gets `reminder_calendar_id TEXT` (an `EKCalendar.calendarIdentifier`), NOT `reminder_uuid` — because Projects map to whole calendars under the new architecture, not to single reminders. Tests and migration logic below already reflect this.

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
async def test_project_has_reminder_calendar_id_column(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(project)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "reminder_calendar_id" in cols


@pytest.mark.asyncio
async def test_reminder_columns_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await ensure_schema(conn)
        await ensure_schema(conn)
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(task)")
        task_cols = {row[1] for row in await cur.fetchall()}
        cur = await conn.execute("PRAGMA table_info(project)")
        proj_cols = {row[1] for row in await cur.fetchall()}
    assert "reminder_uuid" in task_cols
    assert "reminder_calendar_id" in proj_cols
```

(If `pytest`, `aiosqlite`, `Path`, or `ensure_schema` are not yet imported in the file, add the imports at the top.)

- [ ] **Step 3: Run to verify it fails**

```bash
cd services/api && uv run pytest tests/test_migrations.py -v -k reminder
```

Expected: AssertionError — columns missing.

- [ ] **Step 4: Extend `migrations.py`**

Add inside `ensure_schema`, immediately before `await conn.commit()` at the end:

```python
    if not await _table_has_column(conn, "task", "reminder_uuid"):
        await conn.execute("ALTER TABLE task ADD COLUMN reminder_uuid TEXT")
        await conn.execute(
            "CREATE UNIQUE INDEX idx_task_reminder_uuid "
            "ON task(reminder_uuid) WHERE reminder_uuid IS NOT NULL"
        )
    if not await _table_has_column(conn, "project", "reminder_calendar_id"):
        await conn.execute("ALTER TABLE project ADD COLUMN reminder_calendar_id TEXT")
        await conn.execute(
            "CREATE UNIQUE INDEX idx_project_reminder_calendar_id "
            "ON project(reminder_calendar_id) WHERE reminder_calendar_id IS NOT NULL"
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
git commit -m "feat(reminders): schema migration for reminder linkage columns"
```

---

### Task 11: Extend `Task` and `Project` Pydantic models + repos

> **Amendment 2026-05-30 (afternoon):** Task gets `reminder_uuid: str | None` (an `EKReminder.calendarItemIdentifier`). Project gets `reminder_calendar_id: str | None` (an `EKCalendar.calendarIdentifier`) — different column, different repo method (`set_reminder_calendar_id`), different semantics. Task half of this task is unchanged; Project half differs from the original plan.

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
async def test_project_set_reminder_calendar_id(project_repo: ProjectRepo) -> None:
    p = await project_repo.create(ProjectCreate(name="P1"))
    await project_repo.set_reminder_calendar_id(p.id, "CAL-P1")
    refreshed = await project_repo.get(p.id)
    assert refreshed.reminder_calendar_id == "CAL-P1"


@pytest.mark.asyncio
async def test_project_set_reminder_calendar_id_to_none_clears(project_repo: ProjectRepo) -> None:
    p = await project_repo.create(ProjectCreate(name="P1"))
    await project_repo.set_reminder_calendar_id(p.id, "CAL-X")
    await project_repo.set_reminder_calendar_id(p.id, None)
    refreshed = await project_repo.get(p.id)
    assert refreshed.reminder_calendar_id is None
```

- [ ] **Step 3: Run to verify failures**

```bash
cd services/api && uv run pytest tests/test_task_repo.py tests/test_project_repo.py -v -k "reminder_uuid or reminder_calendar_id"
```

Expected: errors — fields and methods undefined.

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
    reminder_calendar_id: str | None = None
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

Update `_COLUMNS`:

```python
_COLUMNS = (
    "id, name, description, status, priority, "
    "calendar_keywords, goals, target_date, created_at, updated_at, reminder_calendar_id"
)
```

Update `_row_to_project` to set `reminder_calendar_id=row["reminder_calendar_id"]`.

Update the INSERT in `create()`:

```python
            await self._conn.execute(
                f"""
                INSERT INTO project ({_COLUMNS}, name_lower)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                ...
            )
```

Append a new method to `ProjectRepo`:

```python
    async def set_reminder_calendar_id(self, project_id: str, calendar_id: str | None) -> None:
        cur = await self._conn.execute(
            "UPDATE project SET reminder_calendar_id = ?, updated_at = ? WHERE id = ?",
            (calendar_id, _now().isoformat(), project_id),
        )
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("project", project_id)
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/test_task_repo.py tests/test_project_repo.py tests/test_routers_projects.py tests/test_routers_tasks.py -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
cd ../..
git add services/api/src/irma_api/models \
        services/api/src/irma_api/store/repos \
        services/api/tests/test_task_repo.py \
        services/api/tests/test_project_repo.py
git commit -m "feat(reminders): persist linkage columns on Task and Project rows"
```

---

### Task 12: Pure sync planner — `plan(irma, helper_calendars) -> SyncPlan`

> **Amendment 2026-05-30 (afternoon):** wholesale rewrite. Under the new architecture, projects map to whole `EKCalendar`s, not to parent reminders. The planner now emits *both* calendar-level operations (create/rename/delete) and per-reminder ones, plus structural operations on Irma's side (unlink a project, rename a project, move a task between projects). The helper-side input is no longer a flat reminder list — it's a list of `HelperCalendarSnap`, one per `Irma · *` calendar discovered on the phone.

**Files:**
- Create: `services/api/src/irma_api/integrations/reminders/planner.py`
- Create: `services/api/tests/integrations/test_reminders_planner.py`

### Algorithm overview (read this before writing code)

The planner is a pure function:

```python
def plan(
    irma: IrmaSnapshot,
    helper_calendars: list[HelperCalendarSnap],
    *,
    calendar_prefix: str = "Irma · ",
    paused_prefix: str = "⏸ ",
) -> SyncPlan:
```

Two passes:

**Pass 1 — calendar reconcile.** For each `Project` in Irma:
1. **Archived project + linked calendar exists on phone** → emit `DeleteCalendar(calendar_id)`. Skip its reminders.
2. **Active/paused project, no `reminder_calendar_id` set** → emit `CreateCalendar(project.id, expected_title)`. Defer this project's reminder sync to the next cycle (the calendar id will be set after the apply).
3. **Active/paused project, `reminder_calendar_id` set but calendar not on phone** → user deleted the list; emit `CreateCalendar(project.id, expected_title)` to recreate. Defer reminder sync.
4. **Active/paused project, calendar exists on phone**:
   - If `phone_title` does **not** start with `calendar_prefix` → user dropped the prefix to detach. Emit `UnlinkProject(project.id)`. Skip the calendar's reminders this cycle.
   - Else strip `calendar_prefix` and any leading `paused_prefix` → `phone_inner_name`.
     - If `phone_inner_name != project.name` → emit `RenameProject(project.id, phone_inner_name)` (phone wins on the project's user-visible name).
     - Compute `expected_title = calendar_prefix + (paused_prefix if paused else "") + new_or_existing_name`.
     - If `phone_title != expected_title` → emit `RenameCalendar(calendar_id, expected_title)` (Irma authoritative for pause prefix and for normalization).
     - Then sync this calendar's reminders (pass 2).

Calendars on the phone that don't match any Project's `reminder_calendar_id` are **ignored entirely** — including their reminders. (Per spec: "to adopt, create the matching Project in Irma; next sync links it.")

**Pass 2 — reminder reconcile.** For each linked `(Project, calendar)` pair from pass 1 (those not archived/unlinked/awaiting-create):

Iterate through tasks where `task.project_id == project.id`:
- `task.reminder_uuid is None` → emit `CreateRemoteReminder(task.id, calendar.id, fields_from_task)`.
- `task.reminder_uuid` present and **found in this calendar** → compare timestamps:
  - `helper_rem.last_modified > task.updated_at` → emit `PatchLocalTask(task.id, fields where helper differs)`.
  - Else → if any field actually differs, emit `PatchRemoteReminder(task.id, calendar.id, reminder_uuid, fields where Irma differs)`.
- `task.reminder_uuid` present and **NOT in this calendar but found in another linked calendar** (where that other calendar maps to a different Project) → emit `MoveTask(task.id, dest_project.id)`. Reminder-content patches deferred to the next sync.
- `task.reminder_uuid` present and **not in any helper calendar** → phone deleted it. Emit `DeleteLocalTask(task.id)`.

Iterate through this calendar's reminders:
- If `reminder.uuid` is already linked to some Irma task: handled above (skip).
- Else: phone-created reminder in this calendar. Emit `CreateLocalTask(project.id, reminder.uuid, fields)`.

### Dataclasses (the interface)

`services/api/src/irma_api/integrations/reminders/planner.py` starts with these definitions — the implementer doesn't need to redesign them:

```python
"""Pure-function reconciliation planner. No I/O, no async, no clock.

The sync engine calls `plan(...)` between the snapshot and apply passes.
Output is a SyncPlan — a description of mutations on both sides — that
the engine then executes idempotently.

Architecture: Projects map 1:1 to EKCalendars named "Irma · <name>";
Tasks are flat reminders within their project's calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from irma_api.integrations.reminders.models import (
    HelperReminder,
    ReminderFields,
)
from irma_api.models.project import ProjectStatus
from irma_api.models.task import TaskStatus

_DEFAULT_CALENDAR_PREFIX = "Irma · "
_DEFAULT_PAUSED_PREFIX = "⏸ "


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IrmaProjectSnap:
    id: str
    name: str
    status: ProjectStatus
    reminder_calendar_id: str | None
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
class HelperCalendarSnap:
    """One Irma-prefixed calendar on the phone + its reminders."""

    calendar_id: str
    title: str
    reminders: list[HelperReminder]


# ---------------------------------------------------------------------------
# Calendar-level operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateCalendar:
    irma_project_id: str
    title: str


@dataclass(frozen=True)
class RenameCalendar:
    calendar_id: str
    new_title: str


@dataclass(frozen=True)
class DeleteCalendar:
    calendar_id: str


@dataclass(frozen=True)
class UnlinkProject:
    """Clear `Project.reminder_calendar_id` without touching the phone calendar."""

    irma_project_id: str


@dataclass(frozen=True)
class RenameProject:
    """Phone-side calendar rename propagated back to `Project.name`."""

    irma_project_id: str
    new_name: str


# ---------------------------------------------------------------------------
# Reminder-level operations (remote = Reminders side, local = Irma DB)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateRemoteReminder:
    irma_task_id: str
    calendar_id: str
    fields: ReminderFields


@dataclass(frozen=True)
class PatchRemoteReminder:
    irma_task_id: str
    calendar_id: str
    reminder_uuid: str
    fields: ReminderFields


@dataclass(frozen=True)
class DeleteRemoteReminder:
    calendar_id: str
    reminder_uuid: str


@dataclass(frozen=True)
class CreateLocalTask:
    project_id: str
    reminder_uuid: str
    title: str
    notes: str
    due_date: date | None
    scheduled_for: date | None
    is_completed: bool


@dataclass(frozen=True)
class PatchLocalTask:
    task_id: str
    title: str | None = None
    notes: str | None = None
    due_date: date | None = None
    scheduled_for: date | None = None
    is_completed: bool | None = None


@dataclass(frozen=True)
class DeleteLocalTask:
    task_id: str


@dataclass(frozen=True)
class MoveTask:
    """Task moved between Irma projects because its reminder lives in a different calendar now."""

    task_id: str
    new_project_id: str


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass
class SyncPlan:
    create_calendars: list[CreateCalendar] = field(default_factory=list)
    rename_calendars: list[RenameCalendar] = field(default_factory=list)
    delete_calendars: list[DeleteCalendar] = field(default_factory=list)
    unlink_projects: list[UnlinkProject] = field(default_factory=list)
    rename_projects: list[RenameProject] = field(default_factory=list)

    create_remote_reminders: list[CreateRemoteReminder] = field(default_factory=list)
    patch_remote_reminders: list[PatchRemoteReminder] = field(default_factory=list)
    delete_remote_reminders: list[DeleteRemoteReminder] = field(default_factory=list)

    create_local_tasks: list[CreateLocalTask] = field(default_factory=list)
    patch_local_tasks: list[PatchLocalTask] = field(default_factory=list)
    delete_local_tasks: list[DeleteLocalTask] = field(default_factory=list)

    move_tasks: list[MoveTask] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entrypoint (implement this)
# ---------------------------------------------------------------------------


def plan(
    irma: IrmaSnapshot,
    helper_calendars: list[HelperCalendarSnap],
    *,
    calendar_prefix: str = _DEFAULT_CALENDAR_PREFIX,
    paused_prefix: str = _DEFAULT_PAUSED_PREFIX,
) -> SyncPlan:
    """See docstring at top of module + the algorithm overview in the plan."""
    raise NotImplementedError  # remove once implemented
```

- [ ] **Step 1: Write the failing tests (cover each algorithm branch)**

`services/api/tests/integrations/test_reminders_planner.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from irma_api.integrations.reminders.models import HelperReminder
from irma_api.integrations.reminders.planner import (
    HelperCalendarSnap,
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
    *, pid: str, name: str = "Alpha",
    cal_id: str | None = None,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    updated: datetime = T0,
) -> IrmaProjectSnap:
    return IrmaProjectSnap(
        id=pid, name=name, status=status,
        reminder_calendar_id=cal_id, updated_at=updated,
    )


def _task(
    *, tid: str, pid: str, title: str = "t",
    status: TaskStatus = TaskStatus.TODO,
    uuid: str | None = None, updated: datetime = T0,
    due: date | None = None, sched: date | None = None,
    notes: str = "",
) -> IrmaTaskSnap:
    return IrmaTaskSnap(
        id=tid, project_id=pid, title=title, status=status,
        reminder_uuid=uuid, updated_at=updated,
        due_date=due, scheduled_for=sched, notes=notes,
    )


def _rem(
    *, uuid: str, title: str = "r",
    completed: bool = False, modified: datetime = T0,
    due: date | None = None, start: date | None = None,
    notes: str = "",
) -> HelperReminder:
    return HelperReminder(
        uuid=uuid, title=title, notes=notes,
        due_date=due, start_date=start,
        is_completed=completed, completion_date=None,
        last_modified=modified,
    )


def _cal(
    *, cid: str, title: str, reminders: list[HelperReminder] | None = None,
) -> HelperCalendarSnap:
    return HelperCalendarSnap(
        calendar_id=cid, title=title, reminders=reminders or [],
    )


# --- Calendar-level reconcile -------------------------------------------


def test_active_project_with_no_calendar_creates_one() -> None:
    snap = IrmaSnapshot(projects=[_proj(pid="P1", name="Alpha")], tasks=[])
    p = plan(snap, helper_calendars=[])
    assert len(p.create_calendars) == 1
    op = p.create_calendars[0]
    assert op.irma_project_id == "P1"
    assert op.title == "Irma · Alpha"
    # No reminder ops while calendar doesn't yet exist
    assert p.create_remote_reminders == []


def test_archived_project_with_linked_calendar_deletes_it() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", cal_id="CAL-A", status=ProjectStatus.ARCHIVED)],
        tasks=[],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.delete_calendars) == 1
    assert p.delete_calendars[0].calendar_id == "CAL-A"


def test_paused_project_renames_calendar_to_add_prefix() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A",
                        status=ProjectStatus.PAUSED)],
        tasks=[],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.rename_calendars) == 1
    assert p.rename_calendars[0].new_title == "Irma · ⏸ Alpha"
    assert p.rename_projects == []


def test_phone_renamed_calendar_renames_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Beta")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.rename_projects) == 1
    assert p.rename_projects[0].irma_project_id == "P1"
    assert p.rename_projects[0].new_name == "Beta"
    # After the project rename, expected_title = "Irma · Beta" already matches phone
    assert p.rename_calendars == []


def test_phone_dropped_prefix_unlinks_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1")],
    )
    # Phone title lost the prefix → unlinked. Reminders in it must NOT be synced.
    cals = [
        _cal(cid="CAL-A", title="Custom Name",
             reminders=[_rem(uuid="REM-T1", title="x")]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.unlink_projects) == 1
    assert p.unlink_projects[0].irma_project_id == "P1"
    assert p.patch_remote_reminders == []
    assert p.patch_local_tasks == []


def test_phone_deleted_calendar_recreates_it_for_active_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[],
    )
    p = plan(snap, helper_calendars=[])  # phone has none
    assert len(p.create_calendars) == 1
    assert p.create_calendars[0].title == "Irma · Alpha"


def test_phone_calendar_without_matching_project_is_ignored() -> None:
    snap = IrmaSnapshot(projects=[], tasks=[])
    cals = [
        _cal(cid="CAL-X", title="Irma · Stranger",
             reminders=[_rem(uuid="REM-1", title="ignored")]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert p.create_calendars == []
    assert p.create_local_tasks == []
    assert p.delete_calendars == []


# --- Reminder-level reconcile -------------------------------------------


def test_irma_only_task_with_linked_calendar_creates_remote_reminder() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", title="hello")],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.create_remote_reminders) == 1
    op = p.create_remote_reminders[0]
    assert op.irma_task_id == "T1"
    assert op.calendar_id == "CAL-A"
    assert op.fields.title == "hello"


def test_both_sides_match_no_ops() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", title="match", updated=T0)],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-T1", title="match", modified=T0),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert p.patch_remote_reminders == []
    assert p.patch_local_tasks == []
    assert p.create_remote_reminders == []
    assert p.create_local_tasks == []


def test_phone_newer_patches_local() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", title="old", updated=T0)],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-T1", title="new", modified=T1),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.patch_local_tasks) == 1
    op = p.patch_local_tasks[0]
    assert op.task_id == "T1"
    assert op.title == "new"


def test_irma_newer_patches_remote() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", title="new", updated=T2)],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-T1", title="old", modified=T1),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.patch_remote_reminders) == 1
    op = p.patch_remote_reminders[0]
    assert op.reminder_uuid == "REM-T1"
    assert op.fields.title == "new"


def test_phone_deleted_reminder_deletes_local() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-DELETED")],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha", reminders=[])]
    p = plan(snap, helper_calendars=cals)
    assert len(p.delete_local_tasks) == 1
    assert p.delete_local_tasks[0].task_id == "T1"


def test_phone_moved_reminder_to_other_calendar_moves_local() -> None:
    snap = IrmaSnapshot(
        projects=[
            _proj(pid="P1", name="Alpha", cal_id="CAL-A"),
            _proj(pid="P2", name="Beta",  cal_id="CAL-B"),
        ],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1")],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[]),  # T1 gone from here
        _cal(cid="CAL-B", title="Irma · Beta", reminders=[
            _rem(uuid="REM-T1"),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.move_tasks) == 1
    assert p.move_tasks[0].task_id == "T1"
    assert p.move_tasks[0].new_project_id == "P2"
    # No DELETE — task survived the move
    assert p.delete_local_tasks == []


def test_phone_created_reminder_in_known_calendar_creates_local_task() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-X", title="from-phone"),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.create_local_tasks) == 1
    op = p.create_local_tasks[0]
    assert op.project_id == "P1"
    assert op.reminder_uuid == "REM-X"
    assert op.title == "from-phone"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_planner.py -v
```

Expected: every test fails — `plan()` raises `NotImplementedError`.

- [ ] **Step 3: Implement `plan()`**

Replace the `raise NotImplementedError` in `planner.py` with an implementation that satisfies every test above, following the algorithm overview at the top of this task. Two passes (calendar reconcile, then reminder reconcile), with the per-test branches handled explicitly. Keep the function pure — no I/O, no clock — so it stays unit-testable.

A few implementation hints:
- Build these indexes up front: `proj_by_id`, `proj_by_calendar_id`, `cal_by_id` (skipping ignored unmatched calendars), `tasks_by_project_id`, and a global `rem_to_calendar` map so the "moved between calendars" branch can find a reminder's new home in O(1).
- Compute `expected_title(project)` as a small helper: `f"{prefix}{paused_prefix if paused else ''}{name}"`.
- For the per-reminder-content diff in patch ops, only set fields where the two sides actually differ — emit `ReminderFields()` with `None`s elsewhere; if every field would be `None`, skip the patch entirely.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_planner.py -v
```

Expected: all 14 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations/reminders/planner.py \
        services/api/tests/integrations/test_reminders_planner.py
git commit -m "feat(reminders): per-calendar reconciliation planner"
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

> **Amendment 2026-05-30 (afternoon):** wholesale rewrite. The service no longer holds a single `calendar_id`; it discovers Irma's calendars on each tick via `bridge.list_calendars(prefix)` and operates per-project-per-calendar. The `_apply` method is rewritten as a four-phase pipeline (calendar reconcile → per-project snapshot → per-project mutate → write-back). `SyncStats` gains calendar-level counters.

**Files:**
- Create: `services/api/src/irma_api/integrations/reminders/sync.py`
- Create: `services/api/tests/integrations/test_reminders_sync.py`

### Service shape

The constructor no longer takes a `calendar_id`:

```python
class ReminderSyncService:
    def __init__(
        self,
        *,
        project_repo: ProjectRepo,
        task_repo: TaskRepo,
        bridge: ReminderBridge,
        calendar_prefix: str = "Irma · ",
    ) -> None: ...
```

`SyncStats` (extended):

```python
@dataclass
class SyncStats:
    # calendar-level
    created_calendars: int = 0
    renamed_calendars: int = 0
    deleted_calendars: int = 0
    unlinked_projects: int = 0
    renamed_projects: int = 0
    # reminder-level
    created_remote: int = 0
    patched_remote: int = 0
    deleted_remote: int = 0
    created_local: int = 0
    patched_local: int = 0
    deleted_local: int = 0
    moved_local: int = 0
```

### `_run_once_locked()` outline

```python
async def _run_once_locked(self) -> SyncStats:
    try:
        await ensure_inbox_project(self._projects)
        irma_snap = await self._snapshot_irma()
        helper_calendars = await self._snapshot_helper()
        sync_plan = plan(irma_snap, helper_calendars)
        stats = await self._apply(sync_plan)
        self.last_sync_at = datetime.now(UTC)
        self.last_error = None
        logger.info("reminders.sync.completed", **asdict(stats))
        return stats
    except BridgeError as exc:
        self.last_error = f"{exc.code}: {exc.message}"
        logger.warning("reminders.sync.failed", code=exc.code, message=exc.message)
        return SyncStats()
    except Exception:
        self.last_error = "internal error"
        logger.exception("reminders.sync.crashed")
        return SyncStats()
```

### `_snapshot_helper()` outline

```python
async def _snapshot_helper(self) -> list[HelperCalendarSnap]:
    cals = await self._bridge.list_calendars(prefix=self._calendar_prefix)
    snaps: list[HelperCalendarSnap] = []
    for c in cals:
        reminders = await self._bridge.list(c.calendar_id)
        snaps.append(HelperCalendarSnap(
            calendar_id=c.calendar_id, title=c.title, reminders=reminders,
        ))
    return snaps
```

### `_apply()` algorithm — four phases

**Phase 1 — Structural Irma-side updates** (cheap, no remote I/O):
- For each `UnlinkProject` op: `project_repo.set_reminder_calendar_id(op.irma_project_id, None)`; `stats.unlinked_projects += 1`.
- For each `RenameProject` op: `project_repo.update(op.irma_project_id, ProjectUpdate(name=op.new_name))`; `stats.renamed_projects += 1`.

**Phase 2 — Calendar mutations**:
- For each `CreateCalendar` op: `new_id = bridge.ensure_list(op.title)` → `project_repo.set_reminder_calendar_id(op.irma_project_id, new_id)`. Buffer the newly-created calendar id → project id mapping for phase 3. `stats.created_calendars += 1`.
- For each `RenameCalendar` op: `bridge.rename_calendar(op.calendar_id, op.new_title)`. `stats.renamed_calendars += 1`.
- For each `DeleteCalendar` op: `bridge.delete_calendar(op.calendar_id)`. Also clear the matching project's `reminder_calendar_id` if it still points at this id (project was archived). `stats.deleted_calendars += 1`.

**Phase 3 — Per-calendar reminder batches**: group all reminder ops by `calendar_id`. For each calendar, build one batch of `BatchOp` (creates first, then patches, then deletes), call `bridge.batch(calendar_id, ops)`, and process the results:
- For each `CreateRemoteReminder` op + corresponding result: if `r.ok` and `r.uuid`, `task_repo.set_reminder_uuid(op.irma_task_id, r.uuid)`. `stats.created_remote += 1`.
- For each `PatchRemoteReminder` op + result: `stats.patched_remote += 1` on success. (No write-back needed: the planner already filtered to "Irma authoritative" diffs, so `Task.updated_at` will be re-stamped naturally by the next planner pass when the timestamps match.)
- For each `DeleteRemoteReminder` op + result: `stats.deleted_remote += 1`.

**Phase 4 — Irma-side reminder mutations** (no remote I/O):
- For each `CreateLocalTask` op: `task = task_repo.create(TaskCreate(project_id=op.project_id, title=op.title, notes=op.notes, due_date=op.due_date, scheduled_for=op.scheduled_for, status=DONE if op.is_completed else TODO))`; `task_repo.set_reminder_uuid(task.id, op.reminder_uuid)`; `stats.created_local += 1`.
- For each `PatchLocalTask` op: build a `TaskUpdate` from the non-None fields, plus `status` derived from `is_completed`; `task_repo.update(op.task_id, update)`; `stats.patched_local += 1`.
- For each `MoveTask` op: `task_repo.update(op.task_id, TaskUpdate(project_id=op.new_project_id))` (extend `TaskUpdate` to accept `project_id` if it doesn't already; see implementation note). `stats.moved_local += 1`.
- For each `DeleteLocalTask` op: `task_repo.delete(op.task_id)`; `stats.deleted_local += 1`.

### Implementation notes

1. `TaskUpdate` (defined in `models/task.py`) does NOT currently accept `project_id`. Either (a) extend it to allow reattribution (add `project_id: str | None = None`) and update `TaskRepo.update` to handle it, or (b) add a new repo method `task_repo.set_project(task_id, new_project_id)`. Pick (b) — keeps `TaskUpdate` semantics focused on user-visible task fields.
2. The Phase-2 calendar creates use `bridge.ensure_list(title)` — the title already includes the `Irma · ` prefix (planner emits the full title). `ensure_list` is idempotent so even if a calendar with that exact title already exists on phone (which the planner shouldn't have asked us to create), we just get back its id.
3. There's a deliberate asymmetry: in Phase 2 we `set_reminder_calendar_id` immediately after creating the calendar so the next tick sees the link. In Phase 3 the per-calendar batch operates on the *current* `calendar_id` from the plan (which has the new id when emitted by Phase 2). The simplest implementation: do Phase 2 first, then re-derive Phase 3 batch grouping. Alternatively, after Phase 2, look up each `CreateRemoteReminder.calendar_id` against the newly-stored values and substitute. Either works; pick the one that reads more clearly.
4. The planner emits zero ops for calendars whose `reminder_calendar_id` was just unlinked in Phase 1 (because the snapshot was taken before Phase 1 ran). That's a small inconsistency — but the next sync tick will see the unlinked state and skip those reminders. So one extra cycle for an unlinked project's reminders to stop syncing. Acceptable.

- [ ] **Step 1: Write the failing test (integration via fake helper)**

`services/api/tests/integrations/test_reminders_sync.py`:

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiosqlite
import pytest

from irma_api.integrations.reminders.bridge import ReminderBridge
from irma_api.integrations.reminders.inbox import INBOX_NAME
from irma_api.integrations.reminders.models import BatchOp, ReminderFields
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


def _svc(conn, bridge) -> ReminderSyncService:
    return ReminderSyncService(
        project_repo=ProjectRepo(conn),
        task_repo=TaskRepo(conn),
        bridge=bridge,
    )


@pytest.mark.asyncio
async def test_first_sync_creates_one_calendar_per_project_and_pushes_tasks(
    conn, tmp_path,
) -> None:
    repo = ProjectRepo(conn)
    tasks = TaskRepo(conn)
    p = await repo.create(ProjectCreate(name="Alpha"))
    await tasks.create(TaskCreate(project_id=p.id, title="hello"))

    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    # First sync: creates Inbox project row + "Irma · Inbox" calendar +
    # "Irma · Alpha" calendar. Tasks created in the calendar after that.
    stats_1 = await svc.sync_once()
    assert stats_1.created_calendars == 2  # Alpha + Inbox
    # Reminder creation may be deferred to a second pass because Phase 2
    # only just discovered the calendar ids. Acceptable per the algorithm.

    stats_2 = await svc.sync_once()
    assert stats_2.created_remote >= 1   # the "hello" task is now in CAL-Alpha

    refreshed_proj = await repo.get(p.id)
    assert refreshed_proj.reminder_calendar_id is not None

    # Tasks have reminder_uuid
    [refreshed_task] = await tasks.list(project_id=p.id)
    assert refreshed_task.reminder_uuid is not None

    # Helper-side: "Irma · Alpha" calendar contains a "hello" reminder
    cals = await bridge.list_calendars("Irma · ")
    alpha = next(c for c in cals if c.title == "Irma · Alpha")
    rems = await bridge.list(alpha.calendar_id)
    assert any(r.title == "hello" for r in rems)


@pytest.mark.asyncio
async def test_phone_created_reminder_in_alpha_creates_task(
    conn, tmp_path,
) -> None:
    repo = ProjectRepo(conn)
    tasks = TaskRepo(conn)
    p = await repo.create(ProjectCreate(name="Alpha"))

    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    # Push project → creates calendar, sets reminder_calendar_id.
    await svc.sync_once()
    refreshed_proj = await repo.get(p.id)
    cal_id = refreshed_proj.reminder_calendar_id
    assert cal_id is not None

    # Phone-side adds a reminder directly to that calendar.
    await bridge.batch(cal_id, [BatchOp.create_op(ReminderFields(title="from-phone"))])

    # Next sync pulls it as a Task in Alpha.
    stats = await svc.sync_once()
    assert stats.created_local == 1
    assert any(t.title == "from-phone" for t in await tasks.list(project_id=p.id))


@pytest.mark.asyncio
async def test_phone_dropped_prefix_unlinks_project_without_deleting(
    conn, tmp_path,
) -> None:
    repo = ProjectRepo(conn)
    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    p = await repo.create(ProjectCreate(name="Alpha"))
    await svc.sync_once()
    cal_id = (await repo.get(p.id)).reminder_calendar_id
    assert cal_id is not None

    # User renames the calendar on the phone to drop the prefix.
    await bridge.rename_calendar(cal_id, "Just Alpha")

    stats = await svc.sync_once()
    assert stats.unlinked_projects == 1
    assert (await repo.get(p.id)).reminder_calendar_id is None

    # The phone-side calendar still exists (we didn't delete it).
    titles = [c.title for c in await bridge.list_calendars("")]
    assert "Just Alpha" in titles


@pytest.mark.asyncio
async def test_archived_project_deletes_its_calendar(conn, tmp_path) -> None:
    from irma_api.models.project import ProjectStatus, ProjectUpdate

    repo = ProjectRepo(conn)
    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    p = await repo.create(ProjectCreate(name="Alpha"))
    await svc.sync_once()
    cal_id = (await repo.get(p.id)).reminder_calendar_id
    assert cal_id is not None

    # Archive in Irma → next sync deletes the calendar on phone.
    await repo.update(p.id, ProjectUpdate(status=ProjectStatus.ARCHIVED))

    stats = await svc.sync_once()
    assert stats.deleted_calendars == 1
    # Verify calendar gone
    cals = await bridge.list_calendars("Irma · ")
    assert all(c.calendar_id != cal_id for c in cals)


@pytest.mark.asyncio
async def test_coalescing_rerun_flag(conn, tmp_path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)
    calls = 0
    original = svc._run_once_locked

    async def counting() -> SyncStats:
        nonlocal calls
        calls += 1
        return await original()

    monkeypatch.setattr(svc, "_run_once_locked", counting)

    await asyncio.gather(svc.sync_once(), svc.sync_once(), svc.sync_once())
    # First call runs; concurrent calls bounce off the lock, but the rerun
    # flag triggers exactly one follow-up.
    assert calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && uv run pytest tests/integrations/test_reminders_sync.py -v
```

Expected: `ModuleNotFoundError: irma_api.integrations.reminders.sync` (the file doesn't exist yet).

- [ ] **Step 3: Implement `sync.py`**

Write `services/api/src/irma_api/integrations/reminders/sync.py` according to the "Service shape", "_run_once_locked outline", "_snapshot_helper outline", and "Four-phase algorithm" sections above. Hand-roll the apply phases — keep them flat, well-commented, and easy to read. The lock + `pending_rerun` flag implementation can be lifted nearly verbatim from the original Task 14 spec (it didn't change with the architecture pivot):

```python
async def sync_once(self) -> SyncStats:
    if self._lock.locked():
        self._pending_rerun = True
        return SyncStats()
    async with self._lock:
        stats = await self._run_once_locked()
        while self._pending_rerun:
            self._pending_rerun = False
            follow = await self._run_once_locked()
            # accumulate every counter from `follow` into `stats`
        return stats
```

Use `dataclasses.asdict(stats)` to pass to the `logger.info` event so all counters are logged structurally.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integrations/test_reminders_sync.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ../..
git add services/api/src/irma_api/integrations/reminders/sync.py \
        services/api/tests/integrations/test_reminders_sync.py
git commit -m "feat(reminders): ReminderSyncService — calendar reconcile + per-cal batch"
```

---

### Task 15: Settings additions

> **Amendment 2026-05-30 (afternoon):** drop `reminders_calendar_id` — there is no single calendar under the new architecture. Replace with `reminders_linked: bool = False` (flips to true after a successful link) and `reminders_calendar_prefix: str = "Irma · "` (used by the sync service when calling `bridge.list_calendars(prefix=...)`). Keep `reminders_sync_interval_seconds` and `reminders_helper_path` unchanged.

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
    assert s.reminders_linked is False
    assert s.reminders_calendar_prefix == "Irma · "
    assert s.reminders_sync_interval_seconds == 60
    assert isinstance(s.reminders_helper_path, Path)
    assert s.reminders_helper_path.name == "irma-reminders-helper"


def test_reminders_linked_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REMINDERS_LINKED", "true")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.reminders_linked is True
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
    # Flipped to True after a successful link; in-memory only by default.
    reminders_linked: bool = False
    # All Irma-managed reminders lists start with this prefix.
    reminders_calendar_prefix: str = "Irma · "
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
git commit -m "feat(reminders): settings for link state, calendar prefix, helper path"
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

> **Amendment 2026-05-30 (afternoon):** under the new architecture there is no single `Irma` calendar to ensure on link; the sync service handles per-project ensure-list. The link flow now: `request-access` → flip `settings.reminders_linked = True` → construct the sync service via the factory (no `calendar_id` arg) → `sync_once()`. The link response body changes from `{calendar_id}` to `{linked: true}`. The unlink endpoint clears `Task.reminder_uuid` and `Project.reminder_calendar_id` (not `Project.reminder_uuid`).

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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, app


@pytest.mark.asyncio
async def test_link_succeeds_when_helper_grants(client) -> None:
    c, app = client
    fake_bridge = MagicMock()
    fake_bridge.request_access = AsyncMock(return_value=True)
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    app.state.reminder_bridge = fake_bridge
    app.state.reminder_sync_factory = lambda: fake_sync

    resp = await c.post("/api/v1/integrations/reminders/link")
    assert resp.status_code == 200
    assert resp.json()["linked"] is True
    assert app.state.settings.reminders_linked is True
    fake_sync.sync_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_returns_403_when_denied(client) -> None:
    c, app = client
    fake_bridge = MagicMock()
    fake_bridge.request_access = AsyncMock(return_value=False)
    app.state.reminder_bridge = fake_bridge
    app.state.reminder_sync_factory = lambda: MagicMock()

    resp = await c.post("/api/v1/integrations/reminders/link")
    assert resp.status_code == 403
    assert app.state.settings.reminders_linked is False


@pytest.mark.asyncio
async def test_sync_now_returns_stats(client) -> None:
    c, app = client
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock(
        return_value=type("S", (), {
            "created_calendars": 1, "renamed_calendars": 0, "deleted_calendars": 0,
            "unlinked_projects": 0, "renamed_projects": 0,
            "created_remote": 2, "patched_remote": 0, "deleted_remote": 0,
            "created_local": 0, "patched_local": 0, "deleted_local": 0,
            "moved_local": 0,
        })()
    )
    app.state.reminder_sync = fake_sync

    resp = await c.post("/api/v1/integrations/reminders/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created_calendars"] == 1
    assert body["created_remote"] == 2


@pytest.mark.asyncio
async def test_sync_when_unlinked_returns_409(client) -> None:
    c, app = client
    app.state.reminder_sync = None
    resp = await c.post("/api/v1/integrations/reminders/sync")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_unlink_clears_linkage(client) -> None:
    c, app = client
    # Seed: link state on, plus a project + task with linkage set.
    app.state.settings.reminders_linked = True
    conn = app.state.store.connection
    await conn.execute(
        "INSERT INTO project (id, name, name_lower, status, priority, "
        "calendar_keywords, goals, created_at, updated_at, reminder_calendar_id) "
        "VALUES ('P1', 'Alpha', 'alpha', 'active', 2, '[]', '[]', "
        "'2026-05-30T12:00:00', '2026-05-30T12:00:00', 'CAL-A')"
    )
    await conn.execute(
        "INSERT INTO task (id, project_id, title, notes, status, "
        "created_at, updated_at, reminder_uuid) "
        "VALUES ('T1', 'P1', 'hello', '', 'todo', "
        "'2026-05-30T12:00:00', '2026-05-30T12:00:00', 'REM-T1')"
    )
    await conn.commit()

    resp = await c.delete("/api/v1/integrations/reminders/link")
    assert resp.status_code == 204
    assert app.state.settings.reminders_linked is False

    cur = await conn.execute(
        "SELECT reminder_calendar_id FROM project WHERE id = 'P1'"
    )
    row = await cur.fetchone()
    assert row[0] is None

    cur = await conn.execute(
        "SELECT reminder_uuid FROM task WHERE id = 'T1'"
    )
    row = await cur.fetchone()
    assert row[0] is None
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

from dataclasses import asdict
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

if TYPE_CHECKING:
    from irma_api.integrations.reminders.bridge import ReminderBridge
    from irma_api.integrations.reminders.sync import ReminderSyncService

router = APIRouter(prefix="/integrations/reminders", tags=["integrations"])


class LinkResponse(BaseModel):
    linked: bool


class SyncResponse(BaseModel):
    # Calendar-level counters
    created_calendars: int
    renamed_calendars: int
    deleted_calendars: int
    unlinked_projects: int
    renamed_projects: int
    # Reminder-level counters
    created_remote: int
    patched_remote: int
    deleted_remote: int
    created_local: int
    patched_local: int
    deleted_local: int
    moved_local: int


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

    request.app.state.settings.reminders_linked = True
    svc = factory()
    request.app.state.reminder_sync = svc
    await svc.sync_once()
    return LinkResponse(linked=True)


@router.delete("/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(request: Request) -> Response:
    """Clear linkage. Does not delete the macOS Reminders lists themselves."""
    store = request.app.state.store
    conn = store.connection
    await conn.execute("UPDATE task SET reminder_uuid = NULL")
    await conn.execute("UPDATE project SET reminder_calendar_id = NULL")
    await conn.commit()
    request.app.state.settings.reminders_linked = False
    request.app.state.reminder_sync = None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync", response_model=SyncResponse)
async def sync_now(request: Request) -> SyncResponse:
    svc: ReminderSyncService | None = getattr(request.app.state, "reminder_sync", None)
    if svc is None:
        raise HTTPException(status_code=409, detail="reminders integration not linked")
    stats = await svc.sync_once()
    return SyncResponse(**asdict(stats))
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

> **Amendment 2026-05-30 (afternoon):** under the new architecture the test creates one calendar per project (e.g. `Irma-Test-Alpha-<uuid>`, `Irma-Test-Inbox-<uuid>`) and uses a custom `reminders_calendar_prefix` so it doesn't collide with the user's real `Irma · *` lists. Tears down per-project calendars individually.

**Files:**
- Create: `services/api/tests/integrations/test_reminders_e2e.py`

> This test exists to give a manual confidence check once the helper is built and TCC has been granted. It is **opt-in**: only runs when `IRMA_REMINDERS_E2E=1` is set. CI never runs it.

- [ ] **Step 1: Write the test**

```python
"""End-to-end smoke test against the real macOS Reminders database.

Run with:
    cd services/api
    IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py -v

Uses a unique calendar prefix per run (e.g. `IrmaTest-abc12345 · `) so it
won't touch the user's real `Irma · *` lists. Tears down all calendars
matching the prefix on exit.
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
async def test_full_push_creates_per_project_calendars(tmp_path) -> None:
    assert HELPER.exists(), f"build the helper first: {HELPER}"
    test_prefix = f"IrmaTest-{uuid.uuid4().hex[:8]} · "

    bridge = ReminderBridge(binary_path=HELPER)
    status = await bridge.access_status()
    if status != "authorized":
        granted = await bridge.request_access()
        if not granted:
            pytest.skip(f"reminders access status={status}; user must grant access")

    created_ids: list[str] = []
    try:
        async with aiosqlite.connect(tmp_path / "e2e.db") as conn:
            conn.row_factory = aiosqlite.Row
            await ensure_schema(conn)
            projects = ProjectRepo(conn)
            tasks = TaskRepo(conn)
            p = await projects.create(ProjectCreate(name="Alpha"))
            await tasks.create(TaskCreate(project_id=p.id, title="e2e task"))

            svc = ReminderSyncService(
                project_repo=projects, task_repo=tasks,
                bridge=bridge, calendar_prefix=test_prefix,
            )
            await svc.sync_once()  # Phase 1: ensures calendars
            await svc.sync_once()  # Phase 2: pushes the task

            cals = await bridge.list_calendars(test_prefix)
            created_ids = [c.calendar_id for c in cals]
            titles = sorted(c.title for c in cals)
            assert titles == [test_prefix + "Alpha", test_prefix + "Inbox"]

            alpha = next(c for c in cals if c.title == test_prefix + "Alpha")
            rems = await bridge.list(alpha.calendar_id)
            assert any(r.title == "e2e task" for r in rems)
    finally:
        for cid in created_ids:
            try:
                await bridge.delete_calendar(cid)
            except Exception:
                pass
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

> **Amendment 2026-05-30 (afternoon):** README explains the `Irma · <ProjectName>` naming convention — the user will see one list per project + an Inbox list in their Reminders sidebar, not a single "Irma" list. The link response body is now `{"linked": true}`, not `{"calendar_id": "..."}`.

**Files:**
- Modify: `services/api/README.md` (or create if missing)
- Modify: `tools/reminders-helper/README.md`

- [ ] **Step 1: Append to `services/api/README.md`**

If the file doesn't exist, create it; otherwise append a new section:

```markdown
## Apple Reminders sync

Mirrors each `Project` in Irma into its own macOS Reminders list named
**`Irma · <ProjectName>`**, with Tasks as flat reminders inside. The Inbox
project lives in **`Irma · Inbox`**, which is also where phone-captured
quick-adds land. Changes in either place flow back on the next sync
(≤60 s, or instantly via `POST /integrations/reminders/sync`).

In your Reminders sidebar you'll see something like:

    Irma · Inbox
    Irma · Video Model
    Irma · MIT Deep Learning
    ...one entry per active Irma project

Renaming `Irma · X` on the phone to `Irma · Y` renames Project X to Y in
Irma. Renaming it to drop the `Irma · ` prefix unlinks the project (Irma
forgets the calendar; it stays on your phone untouched). Archiving a
project in Irma deletes its phone list.

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

   On success, returns `{"linked": true}` and the Inbox list + lists for
   every active project appear in Reminders.

### Useful commands

| Action | Command |
| --- | --- |
| Force a sync now | `curl -X POST http://127.0.0.1:8765/api/v1/integrations/reminders/sync` |
| Unlink (preserve lists on phone) | `curl -X DELETE http://127.0.0.1:8765/api/v1/integrations/reminders/link` |
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

A scan of the (amended) plan against the (amended) spec's section headings:

| Spec section | Covered by |
| --- | --- |
| Architecture diagram + components | Tasks 1–7 (Swift helper), Task 8 (Python package), Task 17 (router) |
| Sync triggers | Task 19 (periodic), Task 20 (post-write), Task 17 (manual + initial link) |
| Coalescing rule | Task 14 (`asyncio.Lock` + `pending_rerun` test) |
| Calendar-naming convention `Irma · <name>` | Tasks 12 (planner), 14 (service), 15 (settings), 22 (README) |
| Inbox project | Task 13 (`ensure_inbox_project`) — its calendar follows the same `Irma · Inbox` convention via the planner |
| Task field mapping (title/notes/due/scheduled/done) | Task 12 (per-field patch logic), Task 14 (apply phases) |
| Project ↔ calendar mapping (rename, pause, archive) | Task 12 (`test_paused_project_renames_calendar_to_add_prefix`, `test_archived_project_with_linked_calendar_deletes_it`, `test_phone_renamed_calendar_renames_project`, `test_phone_dropped_prefix_unlinks_project`) |
| Phone-initiated semantics (new reminder in `Irma · X` → Task in Project X; orphan list ignored) | Task 12 (`test_phone_created_reminder_in_known_calendar_creates_local_task`, `test_phone_calendar_without_matching_project_is_ignored`) |
| Cross-calendar reminder move | Task 12 (`test_phone_moved_reminder_to_other_calendar_moves_local`) |
| Conflict resolution (last-write-wins) | Task 12 (`test_phone_newer_patches_local`, `test_irma_newer_patches_remote`) |
| Four-pass algorithm | Task 14 (calendar reconcile → snapshot → reminder reconcile → apply) |
| Error handling | Task 9 (`BridgeError` codes), Task 14 (`_run_once_locked` catches BridgeError + generic) |
| TCC + linking flow | Task 6 (`requestFullAccessToReminders` — already committed in `d9e74ad`), Task 17 (link endpoint flips `reminders_linked`) |
| Settings additions | Task 15 (`reminders_linked`, `reminders_calendar_prefix`) |
| API surface | Task 17 (router) + Task 16 (status extension) |
| Helper command surface | Tasks 4–7 (covered by commits `1102b5d`/`f5cf301`/`d9e74ad`); `list-calendars` + `rename-calendar` added in `d9e74ad` |
| Schema migration | Task 10 (`reminder_uuid` on task, `reminder_calendar_id` on project) |
| Linkage persistence | Task 11 |
| Observability (structlog events) | Task 14 (`reminders.sync.completed` with all `SyncStats` counters via `asdict`) |
| Testing strategy | Tasks 8/9/12 (Python unit tests with fake helper), Task 14 (service integration tests), Task 21 (opt-in e2e); Swift side is build-only per the XCTest amendment |
| Risks: phone-deleted calendar | Task 12 (`test_phone_deleted_calendar_recreates_it_for_active_project`); Task 14 Phase 2 recreates |
| Risks: TCC denied | Task 17 (403 response), Task 14 (`BridgeError` short-circuits sync), Task 22 (`tccutil reset` doc) |
| Out-of-scope items (sub-subtasks, trash, live notifications) | Not covered — by design |

**Placeholder scan:** all code blocks are complete. Task 12 deliberately leaves the planner implementation to TDD (raise `NotImplementedError` initially), with the 14 test cases as the executable spec. Task 14 likewise spells out the four phases prose-style and asks the implementer to flatten them into Python; this is intentional — the original full-code-spec approach would have been brittle with the per-calendar batching loop.

**Type consistency:** `SyncStats` fields match between the dataclass declaration (Task 14), the router response model (Task 17), and the post-write helper accounting (Task 20). `IrmaProjectSnap` carries `reminder_calendar_id` (not `reminder_uuid`); `IrmaTaskSnap` carries `reminder_uuid`. `HelperCalendarSnap` is the new top-level input for the planner.
