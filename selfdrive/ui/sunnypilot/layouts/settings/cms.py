"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import platform
from datetime import datetime

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
from openpilot.system.ui.sunnypilot.widgets.list_view import (
  ListItemSP,
  button_item_sp,
  multiple_button_item_sp,
  toggle_item_sp,
  ToggleActionSP,
)
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.scroller_tici import Scroller

DEFAULT_CMS_URL = "https://cms.tnchen.info/active_cms.json"
RADIUS_OPTIONS = ["500m", "800m", "1000m", "1500m"]
RADIUS_VALUES = [500.0, 800.0, 1000.0, 1500.0]

CMS_CATEGORIES = [
  ("1", tr("1: Travel Time")),
  ("2", tr("2: Congestion")),
  ("3", tr("3: Accident")),
  ("4", tr("4: Construction")),
  ("5", tr("5: Parking")),
  ("6", tr("6: Announcement")),
  ("7", tr("7: Emergency")),
]
CATEGORY_MODES = [tr("Off"), tr("Display Only"), tr("Alert")]


class CmsAlertLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else ui_state.params

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _get_url_desc(self) -> str:
    url = self._params.get("CmsAlertUrl") or DEFAULT_CMS_URL
    return f"{tr('Current URL')}: {url}"

  def _get_key_desc(self) -> str:
    key = self._params.get("CmsApiKey") or ""
    return f"{tr('Status')}: {tr('Configured') if key else tr('Not Set')}"

  def _edit_url(self):
    current = self._params.get("CmsAlertUrl") or DEFAULT_CMS_URL
    def _on_url_saved(res, text):
      if res == DialogResult.CONFIRM:
        clean = text.strip() or DEFAULT_CMS_URL
        self._params.put("CmsAlertUrl", clean)
    dialog = InputDialogSP(
      title=tr("active_cms.json API URL"),
      sub_title=tr("Enter full HTTPS URL for CMS data"),
      current_text=current,
      param="CmsAlertUrl",
      callback=_on_url_saved,
    )
    dialog.show()

  def _edit_key(self):
    current = self._params.get("CmsApiKey") or ""
    def _on_key_saved(res, text):
      if res == DialogResult.CONFIRM:
        self._params.put("CmsApiKey", text.strip())
    dialog = InputDialogSP(
      title=tr("Cloudflare x-api-key"),
      sub_title=tr("Enter API Key header value (leave blank if not needed)"),
      current_text=current,
      param="CmsApiKey",
      password_mode=False,
      callback=_on_key_saved,
    )
    dialog.show()

  def _get_enabled_types(self) -> set[str]:
    raw = self._params.get("CmsEnabledTypes")
    try:
      return set(json.loads(raw)) if raw else {"7"}
    except Exception:
      return {"7"}

  def _get_muted_types(self) -> set[str]:
    raw = self._params.get("CmsMutedTypes")
    try:
      return set(json.loads(raw)) if raw else set()
    except Exception:
      return set()

  def _get_category_mode(self, type_key: str) -> int:
    enabled = self._get_enabled_types()
    muted = self._get_muted_types()
    if type_key not in enabled:
      return 0  # Off
    elif type_key in muted:
      return 1  # Display Only
    else:
      return 2  # Alert

  def _on_category_mode_selected(self, type_key: str, index: int):
    enabled = self._get_enabled_types()
    muted = self._get_muted_types()
    if index == 0:  # Off
      enabled.discard(type_key)
      muted.discard(type_key)
    elif index == 1:  # Display Only
      enabled.add(type_key)
      muted.add(type_key)
    elif index == 2:  # Alert
      enabled.add(type_key)
      muted.discard(type_key)
    self._params.put("CmsEnabledTypes", json.dumps(sorted(list(enabled))))
    self._params.put("CmsMutedTypes", json.dumps(sorted(list(muted))))

  def _on_radius_selected(self, index: int):
    if 0 <= index < len(RADIUS_VALUES):
      self._params.put("CmsAlertRadius", str(RADIUS_VALUES[index]))

  def _get_radius_index(self) -> int:
    try:
      val = float(self._params.get("CmsAlertRadius") or 800.0)
      for i, r in enumerate(RADIUS_VALUES):
        if abs(val - r) < 1.0:
          return i
    except Exception:
      pass
    return 1  # default 800m

  def _get_history_desc(self) -> str:
    raw = self._mem_params.get("CmsAlertHistory")
    if not raw:
      return tr("No recent alerts")
    try:
      history = json.loads(raw)
      if not history:
        return tr("No recent alerts")
      latest = history[0]
      ts = latest.get("timestamp", 0)
      time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
      return f"{tr('Latest')}: [{time_str}] {latest.get('text', '')}"
    except Exception:
      return tr("No recent alerts")

  def _view_history_dialog(self):
    raw = self._mem_params.get("CmsAlertHistory")
    content = tr("No recent alerts recorded.")
    if raw:
      try:
        history = json.loads(raw)
        if history:
          lines = []
          for item in history[:10]:
            ts = item.get("timestamp", 0)
            t_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
            lines.append(f"[{t_str}] {item.get('text', '')}")
          content = "\n".join(lines)
      except Exception:
        pass

    gui_app.push_widget(ConfirmDialog(content, tr("Close"), callback=lambda res: None))

  def _initialize_items(self) -> list[Widget]:
    items = []

    # 1. Master Enable Toggle
    items.append(
      toggle_item_sp(
        title=tr("Enable CMS Alert"),
        description=tr("Displays real-time CMS traffic information when entering the alert radius of highway signs."),
        param="CmsAlertEnabled",
      )
    )

    # 2. API URL setting
    self._url_item = button_item_sp(
      title=tr("active_cms.json URL"),
      button_text=tr("EDIT"),
      description=self._get_url_desc,
      callback=self._edit_url,
    )
    items.append(self._url_item)

    # 3. API Key setting
    self._key_item = button_item_sp(
      title=tr("API Key (x-api-key)"),
      button_text=lambda: tr("CHANGE") if (self._params.get("CmsApiKey") or "").strip() else tr("SET"),
      description=self._get_key_desc,
      callback=self._edit_key,
    )
    self._key_item.action_item.set_value(lambda: tr("Configured") if (self._params.get("CmsApiKey") or "").strip() else tr("Not Set"))
    items.append(self._key_item)

    # 4. Alert Radius buttons
    items.append(
      multiple_button_item_sp(
        title=tr("Alert Radius"),
        description=tr("Distance threshold to trigger CMS popup alerts."),
        buttons=RADIUS_OPTIONS,
        selected_index=self._get_radius_index(),
        callback=self._on_radius_selected,
      )
    )

    # 5. Connection Status
    items.append(
      text_item(
        tr("API Connection Status"),
        lambda: self._mem_params.get("CmsFetchStatus") or tr("Waiting for updates..."),
      )
    )

    # 6. Recent Alert History
    items.append(
      button_item_sp(
        title=tr("Recent Alert History"),
        button_text=tr("VIEW"),
        description=self._get_history_desc,
        callback=self._view_history_dialog,
      )
    )

    # 7. Category Controls (7 Categories: Off / Display Only / Alert)
    for type_key, type_label in CMS_CATEGORIES:
      item = multiple_button_item_sp(
        title=type_label,
        description=tr("Select mode: Off (Disabled), Display Only (Silent card), Alert (Sound + Card)"),
        buttons=CATEGORY_MODES,
        button_width=160,
        selected_index=self._get_category_mode(type_key),
        callback=lambda idx, k=type_key: self._on_category_mode_selected(k, idx),
      )
      items.append(item)

    return items

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
