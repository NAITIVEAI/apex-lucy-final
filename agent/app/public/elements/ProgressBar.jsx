import React from "react";
import { Progress } from "@/components/ui/progress";

export default function ProgressBar({ label = "Working...", value = 0 }) {
  return (
    <div style={{ width: "100%", padding: "8px 0" }}>
      <div style={{ marginBottom: 6, fontSize: 12, opacity: 0.75 }}>{label}</div>
      <Progress value={value} />
    </div>
  );
}
