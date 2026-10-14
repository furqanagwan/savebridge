namespace SaveBridge.Pages;

/// <summary>What the window asks of a page for controller and keyboard use.</summary>
public interface IAppPage
{
    /// <summary>Y on a controller, F5 on a keyboard.</summary>
    Task RefreshAsync() => Task.CompletedTask;

    /// <summary>Put focus on the page's main control after navigating, so the D-pad starts there.</summary>
    void FocusDefault();
}
