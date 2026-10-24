import Image from "next/image";

import { asset } from "@/lib/assets";

interface AgentFaceProps {
  size?: number;
  active?: boolean;
}

export function AgentFace({ size = 40, active = false }: AgentFaceProps) {
  return (
    <span
      className="avatar-core inline-block"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        boxShadow: active ? "0 0 18px rgba(34, 211, 238, 0.45)" : "0 0 12px rgba(34, 211, 238, 0.2)",
      }}
    >
      <span
        className="relative z-[1] block overflow-hidden"
        style={{ width: "100%", height: "100%", borderRadius: "inherit" }}
      >
        <Image
          src={asset("/agentic-ai.jpg")}
          alt=""
          aria-hidden="true"
          width={735}
          height={490}
          className="object-cover"
          style={{
            width: "100%",
            height: "100%",
            objectPosition: "50% 50%",
            transform: "scale(1.9)",
            transformOrigin: "50% 32%",
          }}
        />
      </span>
    </span>
  );
}
