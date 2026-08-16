import SwiftUI

struct InputPill: View {
    @Bindable var viewModel: NotchViewModel
    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 8) {
            // Microphone button
            Button(action: {
                viewModel.toggleVoiceInput()
            }) {
                ZStack {
                    Image(systemName: viewModel.isRecording ? "mic.fill" : "mic")
                        .font(.system(size: 16))
                        .foregroundStyle(
                            viewModel.isRecording ? Color.red : Theme.secondaryText
                        )
                    if viewModel.isRecording {
                        Circle()
                            .stroke(Color.red, lineWidth: 2)
                            .frame(width: 26, height: 26)
                            .opacity(0.6)
                    }
                }
            }
            .buttonStyle(.plain)
            .help(viewModel.isRecording ? "Нажми чтобы остановить" : "Голосовой ввод")

            TextField(viewModel.inputPlaceholder, text: $viewModel.inputText)
                .textFieldStyle(.plain)
                .font(Theme.bodyFont)
                .foregroundStyle(Theme.primaryText)
                .focused($isFocused)
                .onSubmit {
                    viewModel.sendMessage()
                }
                .disabled(viewModel.isRecording)

            // Send button
            Button(action: { viewModel.sendMessage() }) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 24))
                    .foregroundStyle(
                        viewModel.inputText.isEmpty
                            ? Theme.secondaryText
                            : Theme.accentColor
                    )
            }
            .buttonStyle(.plain)
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(.horizontal, 14)
        .frame(height: Theme.inputPillHeight)
        .background(
            Capsule()
                .fill(Theme.pillBackground)
                .overlay(
                    Capsule()
                        .strokeBorder(
                            viewModel.isRecording ? Color.red.opacity(0.5) :
                                (isFocused ? Theme.accentColor.opacity(0.5) : Theme.pillBorder),
                            lineWidth: viewModel.isRecording ? 2 : 1
                        )
                )
        )
    }
}
