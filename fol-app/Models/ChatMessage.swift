import Foundation

// MARK: - Message Sender

enum MessageSender: String, Codable {
    case user
    case twin
}

// MARK: - Message Content

enum MessageContent: Codable {
    case text(String)
    case toolCall(tool: String, args: [String: String], result: String?, progress: String?)
    case component(A2UIPayload)
}

// MARK: - Chat Message

struct ChatMessage: Identifiable, Codable {
    let id: UUID
    let sender: MessageSender
    var content: MessageContent
    let timestamp: Date
}
