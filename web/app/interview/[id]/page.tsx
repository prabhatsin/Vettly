"use client";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track } from "livekit-client";
import Nav from "@/components/Nav";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";

type TokenResponse = { token: string; url: string; room: string };
type Status = "idle" | "connecting" | "live" | "ended" | "error";
type Message = { role: "you" | "iris"; text: string };

function InterviewContent() {
  const { id } = useParams<{ id: string }>();
  const user = useUser("candidate");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const roomRef = useRef<Room | null>(null);
  const audioBox = useRef<HTMLDivElement>(null);
  const segments = useRef(new Map<string, Message>());
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      roomRef.current?.disconnect();
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function start() {
    setError("");
    setStatus("connecting");
    try {
      const { token, url } = await api<TokenResponse>(
        `/applications/${id}/interview-token`,
        { method: "POST" }
      );

      const room = new Room();
      roomRef.current = room;

      segments.current.clear();
      setMessages([]);

      room.registerTextStreamHandler("lk.transcription", async (reader, participantInfo) => {
        const segmentId = reader.info.attributes?.["lk.segment_id"] ?? reader.info.id;
        const role = participantInfo.identity === room.localParticipant.identity ? "you" : "iris";


        let text = role === "iris" ? segments.current.get(segmentId)?.text ?? "" : "";

        for await (const chunk of reader) {
          text += chunk;
          segments.current.set(segmentId, { role, text });
          setMessages(Array.from(segments.current.values()));
        }
      });

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) {
          audioBox.current?.appendChild(track.attach());
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach((el) => el.remove());
      });
      room.on(RoomEvent.Disconnected, () => setStatus("ended"));

      await room.connect(url, token);
      await room.localParticipant.setMicrophoneEnabled(true);
      setStatus("live");
    } catch (e) {
      setError((e as Error).message);
      setStatus("error");
    }
  }

  function end() {
    roomRef.current?.disconnect();
  }

  if (!user) return null;
  return (
    <>
      <Nav user={user} />
      <main className="mx-auto max-w-2xl p-4">
        <h1 className="mb-4 text-2xl font-semibold">Interview</h1>
        <div ref={audioBox} />

        {(status === "idle" || status === "error" || status === "ended") && (
          <button className="rounded bg-black px-4 py-2 text-white" onClick={start}>
            {status === "ended" ? "Start again" : "Start interview"}
          </button>
        )}
        {status === "connecting" && <p>Connecting...</p>}
        {status === "live" && (
          <div className="flex items-center gap-4">
            <span className="rounded-full bg-green-600 px-3 py-1 text-sm text-white">
              Live
            </span>
            <button className="underline" onClick={end}>
              End interview
            </button>
          </div>
        )}
        {status === "ended" && <p className="mt-3 text-gray-600">Interview ended.</p>}
        {error && <p className="mt-3 text-red-600">{error}</p>}

        <div className="mt-6 flex max-h-96 flex-col gap-2 overflow-y-auto rounded border p-3">
          {messages.length === 0 && (
            <p className="text-sm text-gray-500">The conversation will appear here.</p>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={`rounded p-2 ${m.role === "you" ? "bg-gray-100" : "bg-blue-50"}`}
            >
              <span className="text-xs font-semibold text-gray-500">
                {m.role === "you" ? "You" : "Iris"}
              </span>
              <p className="text-left">{m.text}</p>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </main>
    </>
  );
}

export default function InterviewPage() {
  return (
    <Suspense fallback={<p className="p-4">Loading...</p>}>
      <InterviewContent />
    </Suspense>
  );
}