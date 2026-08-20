import Foundation

// MARK: - A2UI Protocol Models
// Simplified subset of Google's A2UI v0.8 declarative UI protocol.
// The LLM generates A2UI JSON, the SwiftUI renderer maps it to native views.

// MARK: - Core Types

struct A2UIPayload: Codable {
    let version: String?
    let components: [A2UIComponent]

    init(version: String? = "0.8", components: [A2UIComponent]) {
        self.version = version
        self.components = components
    }
}

struct A2UIComponent: Codable, Identifiable {
    let id: String
    let type: String
    let properties: [String: A2UIValue]
    let parentId: String?
    let actions: [A2UIAction]?

    init(id: String, type: String, properties: [String: A2UIValue] = [:], parentId: String? = nil, actions: [A2UIAction]? = nil) {
        self.id = id
        self.type = type
        self.properties = properties
        self.parentId = parentId
        self.actions = actions
    }
}

struct A2UIAction: Codable, Identifiable {
    let id: String
    let label: String
    let type: String
}

// MARK: - Flexible JSON Value

/// Type-erased JSON value for flexible A2UI component properties.
enum A2UIValue: Codable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case array([A2UIValue])
    case object([String: A2UIValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let b = try? container.decode(Bool.self) {
            self = .bool(b)
        } else if let i = try? container.decode(Int.self) {
            self = .int(i)
        } else if let d = try? container.decode(Double.self) {
            self = .double(d)
        } else if let s = try? container.decode(String.self) {
            self = .string(s)
        } else if let arr = try? container.decode([A2UIValue].self) {
            self = .array(arr)
        } else if let obj = try? container.decode([String: A2UIValue].self) {
            self = .object(obj)
        } else {
            self = .null
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let s): try container.encode(s)
        case .int(let i): try container.encode(i)
        case .double(let d): try container.encode(d)
        case .bool(let b): try container.encode(b)
        case .array(let a): try container.encode(a)
        case .object(let o): try container.encode(o)
        case .null: try container.encodeNil()
        }
    }

    // Convenience accessors
    var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    var intValue: Int? {
        if case .int(let i) = self { return i }
        return nil
    }

    var boolValue: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }

    var arrayValue: [A2UIValue]? {
        if case .array(let a) = self { return a }
        return nil
    }

    var objectValue: [String: A2UIValue]? {
        if case .object(let o) = self { return o }
        return nil
    }
}

// MARK: - Component Type Constants

enum A2UIComponentType {
    static let taskApproval = "TaskApproval"
    static let profileCard = "ProfileCard"
    static let screenshot = "Screenshot"
    static let confirmAction = "ConfirmAction"
    static let actionInfo = "ActionInfo"  // File/code info with animated icon + optional diff
    static let peekNotification = "PeekNotification"  // Level 3: lightweight auto-dismiss notification
    static let riskConfirm = "RiskConfirm"            // Level 4: file mutation confirmation
    static let strictModal = "StrictModal"             // Level 5: dangerous system action modal
}

// MARK: - Convenience Extractors
// These extract typed data from the flexible A2UIValue properties.

struct TaskApprovalData {
    let title: String
    let steps: [(id: Int, text: String)]
    let reorderable: Bool

    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.taskApproval else { return nil }

        self.title = component.properties["title"]?.stringValue ?? "Task Plan"
        self.reorderable = component.properties["reorderable"]?.boolValue ?? true

        guard let stepsArray = component.properties["steps"]?.arrayValue else { return nil }

        self.steps = stepsArray.compactMap { value -> (id: Int, text: String)? in
            guard let obj = value.objectValue,
                  let id = obj["id"]?.intValue,
                  let text = obj["text"]?.stringValue else { return nil }
            return (id: id, text: text)
        }
    }
}

struct ProfileCardData {
    let facts: [(text: String, confirmed: Bool?)]

    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.profileCard else { return nil }
        guard let factsArray = component.properties["facts"]?.arrayValue else { return nil }

        self.facts = factsArray.compactMap { value -> (text: String, confirmed: Bool?)? in
            guard let obj = value.objectValue,
                  let text = obj["text"]?.stringValue else { return nil }
            let confirmed = obj["confirmed"]?.boolValue
            return (text: text, confirmed: confirmed)
        }
    }
}

struct ScreenshotData {
    let imageBase64: String
    let caption: String?

    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.screenshot else { return nil }
        guard let base64 = component.properties["image"]?.stringValue else { return nil }
        self.imageBase64 = base64
        self.caption = component.properties["caption"]?.stringValue
    }
}

struct ConfirmActionData {
    let action: String
    let actionId: String

    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.confirmAction else { return nil }
        guard let action = component.properties["action"]?.stringValue else { return nil }
        self.action = action
        self.actionId = component.properties["actionId"]?.stringValue ?? component.id
    }
}

// MARK: - ActionInfo Data

/// Data for the animated ActionInfoCard — file/code information with optional diff preview.
struct ActionInfoData {
    let fileName: String
    let fileSize: String?
    let fileType: ActionInfoCard.FileType
    let diffPreview: String?
    let caption: String?

    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.actionInfo else { return nil }
        guard let fileName = component.properties["fileName"]?.stringValue else { return nil }
        self.fileName = fileName
        self.fileSize = component.properties["fileSize"]?.stringValue
        self.diffPreview = component.properties["diff"]?.stringValue
        self.caption = component.properties["caption"]?.stringValue

        // Map file extension to FileType
        let ext = (fileName as NSString).pathExtension.lowercased()
        switch ext {
        case "swift", "py", "js", "ts", "tsx", "jsx", "rs", "go", "java", "c", "cpp", "h",
             "rb", "php", "sh", "bash", "zsh", "sql", "html", "css", "scss", "less":
            self.fileType = .code
        case "md", "txt", "pdf", "doc", "docx", "rtf":
            self.fileType = .document
        case "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp":
            self.fileType = .image
        case "mp3", "wav", "m4a", "aac", "ogg", "flac":
            self.fileType = .audio
        case "mp4", "mov", "avi", "mkv", "webm":
            self.fileType = .video
        case "zip", "tar", "gz", "7z", "rar":
            self.fileType = .archive
        default:
            self.fileType = .other
        }
    }
}

// MARK: - Peek Notification Data (Level 3)

/// Data for the lightweight auto-dismissing notification badge.
struct PeekNotificationData {
    let toolName: String
    let actionDescription: String
    
    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.peekNotification else { return nil }
        self.toolName = component.properties["toolName"]?.stringValue ?? "action"
        self.actionDescription = component.properties["action"]?.stringValue ?? "Executing..."
    }
}

// MARK: - Risk Confirm Data (Level 4)

/// Data for the animated confirmation card for file mutations.
struct RiskConfirmData {
    let actionId: String
    let toolName: String
    let actionDescription: String
    let riskLevel: RiskConfirmCard.RiskLevel
    
    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.riskConfirm else { return nil }
        self.actionId = component.properties["actionId"]?.stringValue ?? component.id
        self.toolName = component.properties["toolName"]?.stringValue ?? "unknown"
        self.actionDescription = component.properties["action"]?.stringValue ?? ""
        
        // Map risk level string to enum
        let levelStr = component.properties["riskLevel"]?.stringValue ?? "file_mutation"
        switch levelStr {
        case "data_send":
            self.riskLevel = .dataSend
        case "event_mutation":
            self.riskLevel = .eventMutation
        case "memory_write":
            self.riskLevel = .memoryWrite
        default:
            self.riskLevel = .fileMutation
        }
    }
}

// MARK: - Strict Modal Data (Level 5)

/// Data for the modal-like card for dangerous system actions.
struct StrictModalData {
    let actionId: String
    let toolName: String
    let command: String
    
    init?(from component: A2UIComponent) {
        guard component.type == A2UIComponentType.strictModal else { return nil }
        self.actionId = component.properties["actionId"]?.stringValue ?? component.id
        self.toolName = component.properties["toolName"]?.stringValue ?? "unknown"
        self.command = component.properties["command"]?.stringValue ?? ""
    }
}
