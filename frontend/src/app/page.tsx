"use client";

import Link from "next/link";
import { ArrowUp, Paperclip } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { getHome, type HomeFeed, type HomeTask } from "@/lib/api";
import { DEMO_USER } from "@/lib/nav";

const SAMPLE_TASKS: HomeTask[] = [
  {
    id: "recoveries",
    title: "Scan paid bills for tariff refunds",
    detail: "Look for IEEPA charges suppliers passed through after February 2025.",
    href: "/bill-pay/recoveries",
  },
  {
    id: "receipts",
    title: "2 bills are waiting on a receipt",
    detail: "Card transactions from last week still need a receipt.",
    href: "/expenses",
  },
  {
    id: "card",
    title: "Card ending 4412 expires in December",
    detail: "Replace it before the next team offsite.",
    href: "/cards",
  },
  {
    id: "policy",
    title: "A policy update needs a signature",
    detail: "The travel policy changed the hotel cap to $275.",
    href: "/policy",
  },
];

function localGreeting(now = new Date()) {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function sampleFeed(): HomeFeed {
  return { greeting: localGreeting(), prompt: "What can Ramp help you with?", tasks: SAMPLE_TASKS };
}

export default function HomePage() {
  const [feed, setFeed] = useState<HomeFeed | null>(null);
  const [error, setError] = useState(false);
  const [draft, setDraft] = useState("");
  const [greeting, setGreeting] = useState<string | null>(null);

  useEffect(() => {
    setGreeting(localGreeting());
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const next = await getHome();
        if (!cancelled) {
          setFeed(next);
          setError(false);
        }
      } catch {
        if (!cancelled) {
          setFeed(sampleFeed());
          setError(true);
        }
      }
    }
    load();
    const onReset = () => load();
    window.addEventListener("demo-reset", onReset);
    return () => {
      cancelled = true;
      window.removeEventListener("demo-reset", onReset);
    };
  }, []);

  const heading = greeting ? `${greeting}, ${DEMO_USER.firstName}` : null;

  return (
    <div className="px-8 pt-2 pb-12">
      <h1 className="text-[32px] font-normal tracking-[-0.02em] text-[#1c1c1c]">
        {heading ?? <span className="inline-block h-8 w-72 animate-pulse rounded bg-[#f4f3f1]" />}
      </h1>

      <form
        id="ask"
        className="mt-5 flex items-center gap-3 rounded-lg border border-[#e6e4df] bg-white px-4 shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
        onSubmit={(event) => {
          event.preventDefault();
          toast("Ask Ramp isn't connected in this prototype.");
          setDraft("");
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={feed?.prompt ?? "What can Ramp help you with?"}
          className="h-[52px] min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-[#a3a099]"
        />
        <button
          type="button"
          aria-label="Attach a file"
          onClick={() => toast("Attachments aren't part of this prototype.")}
          className="grid size-8 place-items-center text-[#6f6c66] hover:text-[#1c1c1c]"
        >
          <Paperclip className="size-4" strokeWidth={1.75} />
        </button>
        <button
          type="submit"
          aria-label="Send"
          className="grid size-7 place-items-center rounded-full border border-[#e1dfda] text-[#1c1c1c] hover:bg-[#f4f3f1]"
        >
          <ArrowUp className="size-3.5" strokeWidth={2} />
        </button>
      </form>

      <section className="mt-4 flex min-h-[280px] flex-col rounded-lg border border-[#e6e4df] bg-white">
        {feed && feed.tasks.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-[15px] text-[#1c1c1c]">You&apos;re all caught up!</div>
        ) : feed ? (
          <ul className="divide-y divide-[#f0eeea]">
            {feed.tasks.map((task) => (
              <li key={task.id}>
                <Link href={task.href} className="flex items-center gap-4 px-5 py-4 hover:bg-[#fafaf8]">
                  <span className="min-w-0">
                    <span className="block text-[14.5px] font-medium text-[#1c1c1c]">{task.title}</span>
                    <span className="mt-0.5 block text-[13px] text-[#6f6c66]">{task.detail}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : error ? (
          <div className="flex flex-1 items-center justify-center text-[14px] text-[#6f6c66]">Couldn&apos;t load your tasks.</div>
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <div className="h-4 w-40 animate-pulse rounded bg-[#f4f3f1]" />
          </div>
        )}
      </section>
    </div>
  );
}
