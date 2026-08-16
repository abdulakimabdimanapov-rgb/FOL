"use client";

import { useCallback, useRef, useState } from "react";
import ChatView from "@/components/chat/ChatView";
import { streamChat } from "@/lib/api";

interface ChatMessage {
  id: string;
  role: "twin" | "user";
  content: string;
  timestamp: string;
}

function nowTime(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  // Lazy state initializer — Date.now() is impure, so it runs exactly once
  // (useRef would call it on every render and trip the react-hooks/purity rule).
  const [sessionId] = useState<string>(() => `web-${Date.now().toString(36)}`);
  const abortRef = useRef<AbortController | null>(null);
  const twinIdRef = useRef<string>("");

  const handleSend = useCallback((msg: string) => {
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: msg,
      timestamp: nowTime(),
    };
    const twinId = `t-${Date.now()}`;
    twinIdRef.current = twinId;
    const twinMsg: ChatMessage = {
      id: twinId,
      role: "twin",
      content: "",
      timestamp: nowTime(),
    };

    setMessages((prev) => [...prev, userMsg, twinMsg]);
    setIsThinking(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    void streamChat(
      msg,
      sessionId,
      {
        onToken: (text) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === twinId ? { ...m, content: m.content + text } : m,
            ),
          );
        },
        onState: (state, message) => {
          if (state === "working" || state === "thinking") {
            setIsThinking(true);
          } else if (state === "complete" && message) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === twinId ? { ...m, content: message || m.content } : m,
              ),
            );
          }
        },
        onActivity: (_category, _label) => {
          // Coarse status from the Response Formatter — tool names/args are
          // internal and never reach the UI. The thinking indicator covers
          // the visual state.
        },
        onDone: () => {
          setIsThinking(false);
        },
        onError: (error) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === twinId
                ? { ...m, content: error || "Something went wrong." }
                : m,
            ),
          );
          setIsThinking(false);
        },
      },
      controller.signal,
    );
  }, [sessionId]);

  return (
    <ChatView
      userName="Johnathan"
      vncStreamUrl="http://localhost:8421/stream"
      messages={messages}
      isThinking={isThinking}
      onSendMessage={handleSend}
    />
  );
}
