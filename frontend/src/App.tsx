// App.tsx - The page layout and the list of pages (routes).
import { Route, Routes } from "react-router";
import Header from "./components/Header";
import RequireAuth from "./components/RequireAuth";
import HomePage from "./pages/HomePage";
import InterviewPage from "./pages/InterviewPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <>
      <Header />
      <main className="container">
        <Routes>
          {/* Public: anyone can see the list of interviews. */}
          <Route path="/" element={<HomePage />} />

          {/* Protected: RequireAuth sends logged-out users to log in first.
              ":slug" is a placeholder, e.g. /interviews/backend-python */}
          <Route
            path="/interviews/:slug"
            element={
              <RequireAuth>
                <InterviewPage />
              </RequireAuth>
            }
          />

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </>
  );
}
