// App.tsx - The page layout and the list of pages (routes).
import { Route, Routes } from "react-router";
import Header from "./components/Header";
import RequireAuth from "./components/RequireAuth";
import AttemptPage from "./pages/AttemptPage";
import AttemptReviewPage from "./pages/AttemptReviewPage";
import CommunityPage from "./pages/CommunityPage";
import HomePage from "./pages/HomePage";
import InterviewPage from "./pages/InterviewPage";
import MyInterviewsPage from "./pages/MyInterviewsPage";
import NotFoundPage from "./pages/NotFoundPage";
import SharedAnswerPage from "./pages/SharedAnswerPage";

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
          <Route path="/community" element={<RequireAuth><CommunityPage /></RequireAuth>} />
          <Route path="/community/answers/:answerId" element={<RequireAuth><SharedAnswerPage /></RequireAuth>} />

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </>
  );
}
