import os
from openpilot.common.params_pyx import (
  Params as _NativeParams,
  ParamKeyFlag,
  ParamKeyType,
  UnknownKeyName,
)

assert ParamKeyFlag
assert ParamKeyType
assert UnknownKeyName

CMS_PARAM_DEFAULTS = {
  "CmsAlertEnabled": (ParamKeyType.BOOL, "1"),
  "CmsAlertUrl": (ParamKeyType.STRING, "https://cms.tnchen.info/active_cms.json"),
  "CmsApiKey": (ParamKeyType.STRING, ""),
  "CmsAlertRadius": (ParamKeyType.FLOAT, "800.0"),
  "CmsEnabledTypes": (ParamKeyType.STRING, '["7"]'),
  "CmsMutedTypes": (ParamKeyType.STRING, "[]"),
  "CmsCurrentText": (ParamKeyType.STRING, ""),
  "CmsCurrentDist": (ParamKeyType.STRING, ""),
  "CmsCurrentType": (ParamKeyType.STRING, ""),
  "CmsCurrentId": (ParamKeyType.STRING, ""),
  "CmsFetchStatus": (ParamKeyType.STRING, ""),
  "CmsAlertHistory": (ParamKeyType.JSON, "[]"),
}


class Params(_NativeParams):
  """
  Subclass of native C++ Params that adds transparent pure-Python file-based
  handling for Cms* parameters on precompiled release branches.
  """

  def _is_cms_key(self, key) -> str | None:
    if isinstance(key, bytes):
      k = key.decode("utf-8")
    else:
      k = str(key)
    return k if k.startswith("Cms") else None

  def _cms_file_path(self, key_str: str) -> str:
    base = self.get_param_path()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, key_str)

  def check_key(self, key):
    k = self._is_cms_key(key)
    if k is not None:
      if k in CMS_PARAM_DEFAULTS:
        return k.encode("utf-8")
      raise UnknownKeyName(k.encode("utf-8"))
    return super().check_key(key)

  def get(self, key, block=False, return_default=False):
    k = self._is_cms_key(key)
    if k is not None:
      path = self._cms_file_path(k)
      try:
        with open(path, "r", encoding="utf-8") as f:
          val = f.read()
          if val != "":
            return val
      except (FileNotFoundError, PermissionError):
        pass
      if return_default or k in CMS_PARAM_DEFAULTS:
        return CMS_PARAM_DEFAULTS.get(k, (None, None))[1]
      return None
    return super().get(key, block=block, return_default=return_default)

  def get_bool(self, key, block=False):
    k = self._is_cms_key(key)
    if k is not None:
      val = self.get(k, block=block)
      return val in ("1", 1, True, "True", "true")
    return super().get_bool(key, block=block)

  def put(self, key, dat, block=False):
    k = self._is_cms_key(key)
    if k is not None:
      path = self._cms_file_path(k)
      dat_str = dat.decode("utf-8") if isinstance(dat, bytes) else str(dat)
      tmp_path = path + ".tmp"
      try:
        with open(tmp_path, "w", encoding="utf-8") as f:
          f.write(dat_str)
        os.replace(tmp_path, path)
      except Exception:
        pass
      return
    return super().put(key, dat, block=block)

  def put_bool(self, key, val, block=False):
    k = self._is_cms_key(key)
    if k is not None:
      self.put(k, "1" if val else "0", block=block)
      return
    return super().put_bool(key, val, block=block)

  def remove(self, key):
    k = self._is_cms_key(key)
    if k is not None:
      path = self._cms_file_path(k)
      try:
        os.remove(path)
      except FileNotFoundError:
        pass
      return
    return super().remove(key)

  def all_keys(self, flag=ParamKeyFlag.ALL):
    keys = super().all_keys(flag)
    cms_keys = [k.encode("utf-8") if isinstance(keys[0], bytes) else k for k in CMS_PARAM_DEFAULTS.keys()]
    return list(keys) + [k for k in cms_keys if k not in keys]


if __name__ == "__main__":
  import sys

  params = Params()
  key = sys.argv[1]
  assert params.check_key(key), f"unknown param: {key}"

  if len(sys.argv) == 3:
    val = sys.argv[2]
    print(f"SET: {key} = {val}")
    params.put(key, val, block=True)
  elif len(sys.argv) == 2:
    print(f"GET: {key} = {params.get(key)}")
