using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Web.WebView2.Core;
using XboxAuthNet.OAuth.CodeFlow;

namespace SaveBridge.Services;

/// <summary>The Microsoft sign-in page in a small window; returns the OAuth code when login.live.com redirects.</summary>
public sealed class SignInWindow : IWebUI
{
    readonly DispatcherQueue _ui = DispatcherQueue.GetForCurrentThread();

    public Task<CodeFlowAuthorizationResult> DisplayDialogAndInterceptUri(
        Uri uri, ICodeFlowUrlChecker uriChecker, CancellationToken cancellationToken)
    {
        var done = new TaskCompletionSource<CodeFlowAuthorizationResult>();
        _ui.TryEnqueue(async () =>
        {
            var window = new Window { Title = "Sign in to Xbox" };
            var scale = (App.Window?.Content?.XamlRoot?.RasterizationScale) ?? 1.0;
            window.AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(520 * scale), (int)(720 * scale)));
            var web = new WebView2();
            window.Content = web;
            window.Closed += (_, _) => done.TrySetResult(new CodeFlowAuthorizationResult { Error = "cancelled" });
            window.Activate();
            await web.EnsureCoreWebView2Async();
            web.CoreWebView2.NavigationStarting += (_, e) =>
            {
                var result = uriChecker.GetAuthCodeResult(new Uri(e.Uri));
                if (result.IsEmpty) return;
                e.Cancel = true;
                done.TrySetResult(result);
                window.Close();
            };
            cancellationToken.Register(() => _ui.TryEnqueue(window.Close));
            web.Source = uri;
        });
        return done.Task;
    }

    public Task DisplayDialogAndNavigateUri(Uri uri, CancellationToken cancellationToken) => Task.CompletedTask;
}
