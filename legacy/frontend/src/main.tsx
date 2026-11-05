import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { Workspace } from "./layouts/Workspace";
import { Overview } from "./pages/Overview";
import { Playground } from "./pages/Playground";
import { Evaluations } from "./pages/Evaluations";
import { Traces } from "./pages/Traces";
import { Settings } from "./pages/Settings";
import { Planned } from "./pages/Planned";
import { ModelsProvider } from "./contexts/ModelsContext";
import { Prompts } from "./pages/Prompts";
import { RegressionTests } from "./pages/RegressionTests";
import { KnowledgeBase } from "./pages/KnowledgeBase";
import { AIJudge } from "./pages/AIJudge";
import { JudgeReliability } from "./pages/JudgeReliability";
import { Experiments } from "./pages/Experiments";
import { Agents } from "./pages/Agents";
import { FailureInbox } from "./pages/FailureInbox";
import { Security } from "./pages/Security";
import { Marketing } from "./pages/Marketing";
import { Monitoring } from "./pages/Monitoring";
import "./index.css";
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModelsProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Workspace />}>
            <Route index element={<Overview />} />
            <Route path="playground" element={<Playground />} />
            <Route path="evaluations" element={<Evaluations />} />
            <Route path="traces" element={<Traces />} />
            <Route path="settings" element={<Settings />} />
            <Route path="prompts" element={<Prompts />} />
            <Route path="regression-tests" element={<RegressionTests />} />
            <Route path="knowledge-base" element={<KnowledgeBase />} />
            <Route path="ai-judge" element={<AIJudge />} />
            <Route path="judge-reliability" element={<JudgeReliability />} />
            <Route path="experiments" element={<Experiments />} />
            <Route path="agents" element={<Agents />} />
            <Route path="failure-inbox" element={<FailureInbox />} />
            <Route path="security" element={<Security />} />
            <Route path="marketing" element={<Marketing />} />
            <Route path="monitoring" element={<Monitoring />} />
            <Route path="*" element={<Planned />} />
          </Route>
        </Routes>
        <Toaster position="bottom-right" richColors />
      </BrowserRouter>
    </ModelsProvider>
  </StrictMode>,
);
