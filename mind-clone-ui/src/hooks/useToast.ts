import toast from "react-hot-toast";

type ToastType = "success" | "error" | "info";

export function showToast(message: string, type: ToastType = "info") {
  const opts = {
    style: {
      background: "var(--bg-1, #111a24)",
      color: "var(--text, #e9f2fb)",
      border: "1px solid var(--line, rgba(151,184,211,0.22))",
      borderRadius: "10px",
      fontSize: "0.88rem",
    },
  };

  switch (type) {
    case "success":
      toast.success(message, opts);
      break;
    case "error":
      toast.error(message, opts);
      break;
    default:
      toast(message, opts);
  }
}
