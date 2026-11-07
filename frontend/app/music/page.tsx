import { redirect } from "next/navigation";

// The BGM library now lives in Media Library.
export default function MusicRedirect() {
  redirect("/media");
}
