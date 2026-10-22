import type { Metadata } from "next";

import { WorkflowCanvas } from "@/components/canvas/workflow-canvas";
import { requireUser } from "@/lib/auth";

export const metadata: Metadata = { title: "Canvas · TraceMesh" };

export default async function WorkflowPage({ params }: PageProps<"/workflows/[id]">) {
  const { id } = await params;
  // Verified here, next to the content, not only in the proxy.
  await requireUser(`/workflows/${encodeURIComponent(id)}`);

  return (
    <div className="relative min-h-0 flex-1">
      <WorkflowCanvas workflowId={id} />
    </div>
  );
}
