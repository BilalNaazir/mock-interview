// App.tsx - The page layout and the list of pages (routes).
import { Route, Routes } from "react-router";
import Header from "./components/Header";
import RequireAuth from "./components/RequireAuth";
import AttemptPage from "./pages/AttemptPage";
import AttemptReviewPage from "./pages/AttemptReviewPage";
import HomePage from "./pages/HomePage";
import InterviewPage from "./pages/InterviewPage";
import MyInterviewsPage from "./pages/MyInterviewsPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <>
      <Header />
      <main className="container">
        <Routes>
          {/* Public: anyone can see the list of interviews. */}
          <Route path="/" element={<HomePage />} />

          {/* Everything else is login-only. RequireAuth sends logged-out
              users to log in first, then brings them back. */}
          <Route path="/interviews/:slug" element={<RequireAuth><InterviewPage /></RequireAuth>} />
          <Route path="/attempts/:attemptId" element={<RequireAuth><AttemptPage /></RequireAuth>} />
          <Route path="/attempts/:attemptId/review" element={<RequireAuth><AttemptReviewPage /></RequireAuth>} />
          <Route path="/my-interviews" element={<RequireAuth><MyInterviewsPage /></RequireAuth>} />

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </>
  );
}
