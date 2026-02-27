using System;

namespace PromptTool.Core.Models;

public class InvokeAIJobFailedException : Exception
{
    public GenerationJobInfo? JobInfo { get; }

    public InvokeAIJobFailedException(string message, GenerationJobInfo? jobInfo = null, Exception? inner = null)
        : base(message, inner)
    {
        JobInfo = jobInfo;
    }
}
