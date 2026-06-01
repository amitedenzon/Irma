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
        case .writeOnly: return .authorized  // SDK-26 case; treat as granted
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

    func listCalendars(prefix: String) async throws -> [CalendarSummary] {
        return store.calendars(for: .reminder)
            .filter { $0.title.hasPrefix(prefix) }
            .map { CalendarSummary(calendarId: $0.calendarIdentifier, title: $0.title) }
            .sorted { $0.title < $1.title }
    }

    func renameCalendar(calendarId: String, title: String) async throws -> Bool {
        guard let cal = store.calendar(withIdentifier: calendarId) else {
            throw RemindersClientError.calendarNotFound(calendarId)
        }
        if cal.title == title { return false }
        cal.title = title
        try store.saveCalendar(cal, commit: true)
        return true
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
