export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8471";

export type HomeTask = {
  id: string;
  title: string;
  detail: string;
  href: string;
  amount?: number | null;
};

export type HomeFeed = {
  greeting: string;
  prompt: string;
  tasks: HomeTask[];
};

export async function getHome(): Promise<HomeFeed> {
  const response = await fetch(`${API_URL}/api/home`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("The home feed didn't load.");
  }
  return response.json();
}

export async function resetDemo(): Promise<void> {
  const response = await fetch(`${API_URL}/api/demo/reset`, { method: "POST" });
  if (!response.ok) {
    throw new Error("The demo didn't reset.");
  }
}
