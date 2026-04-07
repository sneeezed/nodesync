# NodeSync — Developer Notes

## After every addon change

Delete the old zip and rebuild it before testing in Blender:

```bash
cd /Users/matiassevak/Desktop/nodesync
rm -f nodesync.zip
zip -r nodesync.zip nodesync/
```

Then reinstall in Blender: **Edit → Preferences → Add-ons → Install** → pick `nodesync.zip`.
