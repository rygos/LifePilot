export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok", commit: process.env.LIFE_PILOT_COMMIT_SHA || null });
}
